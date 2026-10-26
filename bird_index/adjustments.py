"""Non-destructive, versioned tone and crop recipes shared by preview and inference."""
import math

TONE_KEYS = ('brightness', 'contrast', 'highlights', 'shadows')


def recipe(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'version', 'box', *TONE_KEYS}:
        raise ValueError('调整参数含未知字段')
    if value.get('version', 1) != 1:
        raise ValueError('不支持的调整版本')
    result = {'version': 1}
    for key in TONE_KEYS:
        number = value.get(key, 0)
        if type(number) not in (int, float) or not math.isfinite(number) or not -100 <= number <= 100:
            raise ValueError('亮度、对比度、高光和阴影须在 -100～100 之间')
        result[key] = round(number, 3)
    box = value.get('box')
    if box is not None:
        if not isinstance(box, list) or len(box) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in box):
            raise ValueError('框选坐标须为四个有限数值')
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1) or min(x2-x1, y2-y1) < .0001:
            raise ValueError('框选范围无效或太小')
        box = [round(x, 7) for x in box]
    result['box'] = box
    return result


def tone_lut(value):
    r = recipe(value)
    result = []
    for i in range(256):
        y = min(1., i / 255 * 2 ** (r['brightness'] / 50))
        y += .25 * (r['shadows']/100 * (1-y)**3 + r['highlights']/100 * y**3)
        y = (y-.5) * 2 ** (r['contrast']/100) + .5
        result.append(math.floor(max(0., min(1., y))*255+.5))
    return result


def apply_tone(image, value):
    """Always return an owned image; source pixels are never changed in place."""
    return image.point(tone_lut(value) * 3)


def square_input(image):
    """Pad a manual rectangle so CLIP's centre crop cannot cut its subject off."""
    from PIL import Image
    edge = max(image.size)
    canvas = Image.new('RGB', (edge, edge), (114, 114, 114))
    canvas.paste(image, ((edge-image.width)//2, (edge-image.height)//2))
    return canvas
