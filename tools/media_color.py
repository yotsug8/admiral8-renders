"""Explicit SDR encoding for sRGB PNGs from Blender and browser screenshots.

Matrix conversion and stream tags must agree. Tagging BT.709 without converting
RGB with that matrix would shift colors. This does not grade or tone-map images.
Do not use for arbitrary decoded video/HDR without checking its transfer curve.
"""

SRGB_VIDEO_ARGS = (
    '-vf', ('scale=in_range=pc:out_range=tv:out_color_matrix=bt709,'
            'setparams=range=limited:color_primaries=bt709:'
            'color_trc=iec61966-2-1:colorspace=bt709'),
    '-color_range', 'tv', '-colorspace', 'bt709',
    '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1',
)
