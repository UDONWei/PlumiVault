"""阶段 1：有界清单、只读解码、内存裁切、离线候选；不是完整索引程序。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import socket
import sys
import threading
import time

sys.dont_write_bytecode = True
from context_prior import POLICY, load_occurrences, rank_scores, resolve_context, validate_context
FORMATS = {'.arw', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp'}


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def disjoint(*paths):
    resolved = [Path(p).resolve() for p in paths]
    for i, a in enumerate(resolved):
        for b in resolved[i + 1:]:
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise ValueError(f'目录必须互不嵌套: {a}, {b}')


def photo_path(root, relative):
    p = Path(relative)
    if p.is_absolute() or p.drive or '..' in p.parts or ':' in relative:
        raise ValueError('照片路径必须为根目录内的相对路径，禁止 .. 和 ADS')
    result = (root / p).resolve(strict=True)
    if not result.is_relative_to(root) or not result.is_file():
        raise ValueError('照片路径越界或不是文件（含链接越界）')
    if result.suffix.lower() not in FORMATS:
        raise ValueError('不支持的扩展名')
    return result


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path, content=False):
    s = path.stat()
    result = {'size': s.st_size, 'mtime_ns': s.st_mtime_ns}
    if content:
        result['sha256'] = sha256(path)
    return result


def install_guard(output):
    """Python 层额外保护；不声称替代操作系统只读 ACL / 挂载。"""
    def check(p):
        if isinstance(p, (str, bytes, os.PathLike)) and not inside(os.fsdecode(p), output):
            raise PermissionError('验证进程只能写独立输出目录')

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            if (mode and any(c in mode for c in 'wax+')) or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                check(path)
        elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'}:
            check(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            for p in args[:2]:
                check(p)
        elif event in {'socket.connect', 'socket.connect_ex', 'socket.sendto', 'subprocess.Popen', 'os.system'}:
            raise PermissionError('验证进程禁止外部连接和启动子进程')
    sys.addaudithook(audit)


class MemoryMeter:
    """20ms RSS 采样可能漏掉短峰值；Windows 另记进程累计 peak_wset。"""
    def __init__(self):
        import psutil
        self.process = psutil.Process()
        self.stop = threading.Event()
        self.peak = 0
        self.section_peak = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def sample(self):
        rss = self.process.memory_info().rss
        self.peak = max(self.peak, rss)
        self.section_peak = max(self.section_peak, rss)
        return rss

    def _run(self):
        while not self.stop.wait(.02):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()
        self.sample()

    def reset_section(self):
        self.section_peak = self.process.memory_info().rss

    def report(self):
        info = self.process.memory_info()
        return {'rss_sample_peak_bytes': self.peak,
                'section_rss_sample_peak_bytes': self.section_peak,
                'process_lifetime_peak_wset_bytes': getattr(info, 'peak_wset', None),
                'sample_interval_ms': 20}


@contextmanager
def elapsed(result, name):
    start = time.perf_counter()
    try:
        yield
    finally:
        result[name] = result.get(name, 0) + time.perf_counter() - start


def metadata(path):
    import exifread
    with path.open('rb') as f:
        tags = exifread.process_file(f, details=False, extract_thumbnail=False)
    keys = ('Image Make', 'Image Model', 'Image Orientation', 'Image Compression',
            'EXIF DateTimeOriginal')
    return {key: str(tags[key]) for key in keys if key in tags}


def rgb_image(image, info):
    from PIL import ImageCms
    profile = image.info.get('icc_profile')
    if profile:
        try:
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                             ImageCms.createProfile('sRGB'), outputMode='RGB')
            info['color'] = 'ICC 转 sRGB'
        except Exception as e:
            info['color'] = f'ICC 转换失败，按 RGB 读取待复核: {e}'
    else:
        info['color'] = '无 ICC，假定 sRGB（待核对）'
    return image.convert('RGB')


def decode(path, mode, preview_min, info, times, *, half_size=False):
    from PIL import Image, ImageOps
    with elapsed(times, 'metadata_s'):
        try:
            info['exif'] = metadata(path)
        except Exception as e:
            info['metadata_error'] = str(e)
    if path.suffix.lower() != '.arw':
        with elapsed(times, 'decode_s'):
            with Image.open(path) as src:
                info['original_size'] = list(src.size)
                info['orientation'] = src.getexif().get(274)
                info['frames'] = getattr(src, 'n_frames', 1)
                image = rgb_image(ImageOps.exif_transpose(src), info)
            info['decode_route'] = 'ordinary_first_frame'
            return image
    import rawpy
    with rawpy.RawPy() as raw:
        # 只读打开；预览阶段不调用 imread()，避免先完整 unpack RAW。
        with elapsed(times, 'raw_open_s'):
            raw.open_file(str(path))
        info['raw_sizes'] = raw.sizes._asdict()
        info['raw_flip'] = raw.sizes.flip
        source_size = [raw.sizes.width, raw.sizes.height]
        info['oriented_source_size'] = source_size[::-1] if raw.sizes.flip in (5, 6) else source_size
        preview = None
        if mode != 'full':
            with elapsed(times, 'preview_s'):
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        with Image.open(io.BytesIO(thumb.data)) as src:
                            orientation = src.getexif().get(274)
                            preview = rgb_image(ImageOps.exif_transpose(src), info)
                    else:
                        orientation = None
                        preview = Image.fromarray(thumb.data).convert('RGB')
                    info['preview_orientation'] = orientation
                    # 内嵌 JPEG 已有非平凡 EXIF 方向时，不重复应用 LibRaw flip。
                    if orientation in (None, 1):
                        transform = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90,
                                     6: Image.Transpose.ROTATE_270}.get(raw.sizes.flip)
                        if transform is not None:
                            oriented = preview.transpose(transform)
                            preview.close()
                            preview = oriented
                        info['orientation_method'] = 'LibRaw flip；真实预览是否已旋转须人工核对'
                    else:
                        info['orientation_method'] = 'preview EXIF transpose'
                    info['preview_size'] = list(preview.size)
                except Exception as e:
                    info['preview_error'] = f'{type(e).__name__}: {e}'
        use_preview = preview is not None and (mode == 'preview' or (mode == 'auto' and max(preview.size) >= preview_min))
        if use_preview:
            info['decode_route'] = 'embedded_preview'
            return preview
        if preview is not None:
            preview.close()
        if mode == 'preview':
            raise ValueError('预览不可用；preview 模式不静默回退')
        with elapsed(times, 'decode_s'):
            breakdown = info['decode_breakdown'] = {}
            with elapsed(breakdown, 'unpack_s'):
                raw.unpack()
            with elapsed(breakdown, 'postprocess_s'):
                array = raw.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB,
                                        output_bps=8, half_size=half_size, no_auto_bright=True)
            with elapsed(breakdown, 'image_wrap_s'):
                image = Image.fromarray(array)
        info['decode_route'] = 'half_raw_in_memory' if half_size else 'full_raw_in_memory'
        info['color'] = 'LibRaw camera WB / sRGB / 8bit / no auto bright'
        info['orientation_method'] = 'LibRaw postprocess default flip'
        return image


def crop_box(image, box):
    if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
        raise ValueError('裁切框必须是四个有限数值')
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError('裁切框须满足 0<=x1<x2<=1, 0<=y1<y2<=1')
    w, h = image.size
    bounds = (math.floor(x1*w), math.floor(y1*h), math.ceil(x2*w), math.ceil(y2*h))
    return image.crop(bounds), bounds


class LocalBioCLIP:
    def __init__(self, bundle, labels_path, text_features=None, save_features=None):
        """复用 pybioclip 文本模板/分类；覆盖默认下载和 torch.compile。"""
        import torch
        import open_clip
        from bioclip import CustomLabelsClassifier
        bundle = Path(bundle)
        config = json.loads((bundle / 'model.json').read_text(encoding='utf-8-sig'))
        if config['model_id'] != 'imageomics/bioclip' or not config.get('revision'):
            raise ValueError('必须明确初代 BioCLIP 来源和固定 revision')
        weights = (bundle / config['weights']).resolve(strict=True)
        if not weights.is_relative_to(bundle.resolve()) or sha256(weights) != config['sha256']:
            raise ValueError('模型路径或 SHA256 不符')
        labels = json.loads(Path(labels_path).read_text(encoding='utf-8-sig'))
        self.labels = labels['labels']
        if len(self.labels) < 2 or not labels.get('source') or not labels.get('license'):
            raise ValueError('至少两个候选及标签来源、许可；不得使用空模板')
        prompts = [x['prompt'] for x in self.labels]
        if len(set(prompts)) != len(prompts):
            raise ValueError('重复 prompt')
        templates = labels.get('templates')
        features_key = {'labels_sha256': sha256(labels_path), 'weights_sha256': config['sha256'],
                        'templates': templates, 'open_clip': importlib.metadata.version('open-clip-torch'),
                        'pybioclip': importlib.metadata.version('pybioclip')}
        class OfflineClassifier(CustomLabelsClassifier):
            def load_pretrained_model(self, model_str, pretrained_str):
                self.model_str = model_str
                self.pretrained_str = pretrained_str
                self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                    model_str, pretrained=pretrained_str, device='cpu')
                self.model.eval()
            @torch.no_grad()
            def _get_txt_embeddings(self, classnames):
                if text_features:
                    cache = torch.load(text_features, map_location='cpu', weights_only=True)
                    if cache['key'] != features_key or cache['features'].shape != (512, len(classnames)):
                        raise ValueError('文本特征缓存与模型/标签/模板不一致')
                    return cache['features']
                if not templates:
                    return super()._get_txt_embeddings(classnames)
                # 小批量生成文本特征；提示词方案显式写入报告，不冒充默认 80 模板。
                blocks = []
                for start in range(0, len(classnames), 16):
                    names = classnames[start:start+16]
                    texts = [template.format(name) for name in names for template in templates]
                    tokens = self.tokenizer(texts).to(self.device)
                    features = self.model.encode_text(tokens)
                    features = torch.nn.functional.normalize(features, dim=-1)
                    features = features.reshape(len(names), len(templates), -1).mean(dim=1)
                    blocks.append(torch.nn.functional.normalize(features, dim=-1))
                    if start % 160 == 0:
                        print(f'text features {min(start+16,len(classnames))}/{len(classnames)}', file=sys.stderr, flush=True)
                return torch.cat(blocks, dim=0).T.contiguous()
        self.engine = OfflineClassifier(prompts, model_str='ViT-B-16', pretrained_str=str(weights), device='cpu')
        if save_features:
            torch.save({'key': features_key, 'features': self.engine.txt_embeddings}, save_features)
        self.map = dict(zip(prompts, self.labels))
        self.details = {'bundle': config, 'labels_sha256': sha256(labels_path),
                        'label_count': len(prompts), 'labels_source': labels['source'],
                        'labels_license': labels['license'], 'preprocess': str(self.engine.preprocess),
                        'templates': templates or 'pybioclip default 80', 'text_features_reused': bool(text_features),
                        'compile': False, 'batch_size': 1, 'device': 'cpu'}

    def predict(self, image, k):
        import torch
        with torch.inference_mode():
            rows = self.engine.predict([image], k=k, batch_size=1, callback=lambda *_: None)
        return [dict(label=self.map[x['classification']], score=x['score']) for x in rows]

    def all_scores(self, image):
        rows = self.predict(image, len(self.labels))
        by_prompt = {x['label']['prompt']: x['score'] for x in rows}
        return [by_prompt[label['prompt']] for label in self.labels]


def versions():
    result = {}
    for name in ('rawpy', 'numpy', 'Pillow', 'psutil', 'ExifRead', 'torch', 'torchvision', 'pybioclip', 'open-clip-torch'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    try:
        import rawpy
        result['LibRaw'] = list(rawpy.libraw_version)
        result['rawpy_flags'] = rawpy.flags
    except ImportError:
        pass
    return result


def run(args):
    root = args.photos_root.resolve(strict=True)
    output = args.output.resolve()
    if not root.is_dir():
        raise ValueError('照片根目录不存在')
    paths = [root, output]
    if args.model_dir:
        paths.append(args.model_dir.resolve(strict=True))
    disjoint(*paths)
    if args.manifest.resolve().is_relative_to(output) or (args.labels and args.labels.resolve().is_relative_to(output)):
        raise ValueError('输入清单/候选表不能放在新建输出目录内')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    samples = manifest['samples']
    if not 1 <= len(samples) <= args.limit <= 50:
        raise ValueError('清单须含 1 至 limit 张；limit 最大为 50；超量拒绝执行')
    if len({s['path'] for s in samples}) != len(samples):
        raise ValueError('清单路径重复')
    if bool(args.model_dir) != bool(args.labels):
        raise ValueError('model-dir 与 labels 必须同时提供')
    if args.detector_config and (not args.model_dir or args.probe_crops or any(x.get('boxes') for x in samples)):
        raise ValueError('主体模式需模型配置，且不能同时启用固定窗口或人工框')
    if args.detector_config and (inside(args.detector_config,root) or inside(args.detector_config,output)):
        raise ValueError('检测器配置必须位于照片和输出目录之外')
    occurrences = load_occurrences(args.context_priors) if args.context_priors else None
    regions = occurrences['regions'] if occurrences else None
    defaults = manifest.get('capture_context', {})
    validate_context(defaults, regions)
    for sample in samples:
        validate_context(sample.get('capture_context', {}), regions)
    # 输出目录必须全新；不覆盖历史报告，也避免重用已有链接或缓存。
    output.mkdir(parents=True, exist_ok=False)
    for name in ('HF_HOME', 'TORCH_HOME', 'XDG_CACHE_HOME', 'TEMP', 'TMP', 'TMPDIR'):
        os.environ[name] = str(output / 'runtime')
    (output / 'runtime').mkdir()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      TORCH_FORCE_WEIGHTS_ONLY_LOAD='1', OMP_NUM_THREADS=str(args.threads),
                      MKL_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS=str(args.threads))
    install_guard(output)
    import psutil
    report = {'kind': 'stage1_probe', 'environment': platform.platform(), 'python': sys.version,
              'ram_total_bytes': psutil.virtual_memory().total, 'cpu_logical': psutil.cpu_count(),
              'versions': versions(), 'photos_root': str(root), 'settings': vars(args).copy(),
              'manifest_sha256': sha256(args.manifest), 'access_evidence': manifest.get('access_evidence', '未提供'),
              'protection': '只读文件 API + Python 审计；操作系统只读权限须另外验证',
              'detector': '未启用；仅整图与人工框对照，框不是检测结果',
              'score_meaning': '当前候选集合内 softmax，非正确概率；所有候选待人工确认',
              'rows': [], 'model_init_s': None, 'classification': '未运行'}
    report['context_prior'] = {'enabled': occurrences is not None, 'policy': POLICY,
                               'data': {k: v for k, v in occurrences.items() if k != 'species'} if occurrences else None}
    exit_code = 0
    with MemoryMeter() as meter:
        model = None
        detector = None
        try:
            if args.model_dir:
                with elapsed(report, 'imports_s'):
                    import torch
                    torch.set_num_threads(args.threads)
                    torch.set_num_interop_threads(1)
                report['model_init_s'] = 0
                with elapsed(report, 'model_init_s'):
                    model = LocalBioCLIP(args.model_dir, args.labels, args.text_features, output / 'text_features.pt')
                report['model'] = model.details
                if args.save_all_scores:
                    report['score_labels'] = model.labels
                report['classification'] = '已启用，逐图状态见 rows'
                if args.detector_config:
                    from subject_detector import LocalBirdDetector
                    with elapsed(report,'detector_init_s'):
                        detector=LocalBirdDetector(args.detector_config)
                    report['detector']=detector.details
            for index, sample in enumerate(samples):
                meter.reset_section()
                row = {'path': sample['path'], 'truth': sample.get('truth'), 'scenario': sample.get('scenario'),
                       'decode_ok': False, 'status': 'error', 'timings': {}, 'views': []}
                image = None
                path = None
                before = None
                started = time.perf_counter()
                try:
                    path = photo_path(root, sample['path'])
                    before = fingerprint(path, args.hash_samples)
                    if time.time() - path.stat().st_mtime < args.stable_seconds:
                        raise ValueError('文件修改时间太近，稍后重试')
                    row['before'] = before
                    mode = sample.get('raw_mode', args.raw_mode)
                    if mode not in ('auto', 'preview', 'full'):
                        raise ValueError('无效 raw_mode')
                    image = decode(path, mode, args.preview_min, row, row['timings'])
                    if args.similarity_features:
                        from similarity_features import describe
                        with elapsed(row['timings'],'similarity_features_s'):
                            row['similarity']={'whole':describe(image)}
                    row['decoded_size'] = list(image.size)
                    row['decode_ok'] = True
                    row['capture_context'] = resolve_context(defaults, sample.get('capture_context', {}),
                        row.get('exif', {}), root.name, sample['path'], regions)
                    boxes = sample.get('boxes', [])
                    if len(boxes) > 8:
                        raise ValueError('每图最多 8 个人工框')
                    views = [('whole', None)] + [(f'manual_{i+1}', b) for i, b in enumerate(boxes)]
                    if args.probe_crops:
                        views += [('fixed_center', [.25,.25,.75,.75]), ('fixed_tl', [0,0,.6,.6]),
                                  ('fixed_tr', [.4,0,1,.6]), ('fixed_bl', [0,.4,.6,1]), ('fixed_br', [.4,.4,1,1])]
                    if detector:
                        try:
                            with elapsed(row['timings'],'detection_s'):
                                row['detection']=detector.detect(image)
                        except Exception as error:
                            row['detection']={'status':'error','selected_box':None,'message':'检测失败，保留整图待复核','error':str(error)}
                            exit_code=2
                        views=[('subject',row['detection']['selected_box'])] if row['detection']['selected_box'] else [('whole',None)]
                    for name, box in views:
                        view = image
                        entry = {'name': name, 'source': 'whole' if box is None else 'human_box', 'candidates': []}
                        if name=='subject':
                            entry['source']='automatic_bird_detection'
                        if name.startswith('fixed_'):
                            entry['source'] = 'fixed_window_not_detection'
                        try:
                            if box is not None:
                                with elapsed(row['timings'], 'crop_s'):
                                    view, entry['pixel_box'] = crop_box(image, box)
                                entry['normalized_box'] = box
                            entry['size'] = list(view.size)
                            if args.similarity_features:
                                with elapsed(row['timings'],'similarity_features_s'):
                                    row['similarity']['subject']=describe(view)
                            if model:
                                with elapsed(row['timings'], 'classification_s'):
                                    if occurrences is not None or args.save_all_scores:
                                        scores = model.all_scores(view)
                                    else:
                                        entry['candidates'] = model.predict(view, args.top_k)
                                if occurrences is not None or args.save_all_scores:
                                    with elapsed(row['timings'], 'context_ranking_s'):
                                        entry.update(rank_scores(model.labels, scores, row['capture_context'],
                                                                 occurrences, args.top_k))
                                    if args.save_all_scores:
                                        entry['all_visual_scores'] = scores
                            if args.thumbnails:
                                from PIL import Image
                                thumb = view.copy()
                                thumb.thumbnail((args.thumbnail_edge, args.thumbnail_edge), Image.Resampling.LANCZOS)
                                target = output / f'{index+1:03d}_{name}.jpg'
                                thumb.save(target, quality=80)
                                entry['thumbnail'] = {'name': target.name, 'size': list(thumb.size)}
                                thumb.close()
                            row['views'].append(entry)
                        finally:
                            if box is not None and view is not image:
                                view.close()
                    row['status'] = 'needs_review' if model else 'decode_only'
                except Exception as e:
                    row['error'] = f'{type(e).__name__}: {e}'
                    exit_code = 2
                finally:
                    if image:
                        image.close()
                    if path and before:
                        try:
                            row['after'] = fingerprint(path, args.hash_samples)
                            row['source_unchanged'] = before == row['after']
                            if not row['source_unchanged']:
                                row['status'] = 'source_changed'
                                exit_code = 2
                        except Exception as e:
                            row['source_unchanged'] = False
                            row['source_check_error'] = str(e)
                            exit_code = 2
                    row['timings']['total_s'] = time.perf_counter() - started
                    meter.sample()
                    row['memory'] = meter.report()
                    report['rows'].append(row)
                    with (output / 'results.jsonl').open('a', encoding='utf-8') as f:
                        f.write(json.dumps(row, ensure_ascii=False) + '\n')
                if row.get('source_unchanged') is False:
                    report['stopped_reason'] = '样片变化或无法复核，停止本批'
                    break
        except Exception as e:
            report['fatal_error'] = f'{type(e).__name__}: {e}'
            exit_code = 2
        report['memory'] = meter.report()
    report['summary'] = {'requested': len(samples), 'processed': len(report['rows']),
                         'decode_success': sum(r['decode_ok'] for r in report['rows']),
                         'accuracy': None, 'accuracy_reason': '未作人工真值评估'}
    report['generated_files'] = [str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()] + ['report.json']
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'report': str(output / 'report.json'), **report['summary']}, ensure_ascii=False))
    return exit_code


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--photos-root', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--threads', type=int, choices=range(1, 9), default=2)
    p.add_argument('--raw-mode', choices=['auto', 'preview', 'full'], default='auto')
    p.add_argument('--preview-min', type=int, default=1600)
    p.add_argument('--stable-seconds', type=int, default=60)
    p.add_argument('--hash-samples', action='store_true')
    p.add_argument('--thumbnails', action='store_true')
    p.add_argument('--thumbnail-edge', type=int, choices=range(64, 1025), default=512)
    p.add_argument('--model-dir', type=Path)
    p.add_argument('--labels', type=Path)
    p.add_argument('--text-features', type=Path, help='可选：前一轮报告输出的文本特征缓存；读取后检查来源键')
    p.add_argument('--probe-crops', action='store_true', help='加入 5 个固定窗口对照；不是鸟体检测，也不是人工框')
    p.add_argument('--top-k', type=int, choices=range(1, 11), default=5)
    p.add_argument('--context-priors', type=Path, help='可选：有来源的地区/居留类型数据，启用弱辅助排序')
    p.add_argument('--detector-config',type=Path,help='可选：本地鸟体检测配置；每图只保留一个主体或整图回退')
    p.add_argument('--similarity-features',action='store_true',help='仅保存外观数字摘要，用于可恢复相似折叠')
    p.add_argument('--save-all-scores', action='store_true', help='保留全国完整分数向量，供本地复核页调整背景信息；不含照片')
    return p


if __name__ == '__main__':
    try:
        raise SystemExit(run(parser().parse_args()))
    except (ValueError, OSError) as error:
        print(f'配置失败: {error}', file=sys.stderr)
        raise SystemExit(2)
