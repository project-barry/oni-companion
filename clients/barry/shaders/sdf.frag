#version 440
// 0.5 in the atlas is the glyph's outline; every 1/spread of texture value is one atlas pixel of distance.
// The distance is turned into screen pixels, so the edge is anti-aliased over exactly one screen pixel.
layout(location = 0) in vec2 coord;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 uvRect;
    vec4 color;
    vec4 chan;
    float spread;
    float sdfScale;
} ubuf;
layout(binding = 1) uniform sampler2D src;
void main() {
    float t = dot(texture(src, coord), ubuf.chan);
    float distPx = (t - 0.5) * ubuf.spread * ubuf.sdfScale;
    float a = clamp(distPx + 0.5, 0.0, 1.0) * ubuf.color.a * ubuf.qt_Opacity;
    fragColor = vec4(ubuf.color.rgb * a, a);
}
