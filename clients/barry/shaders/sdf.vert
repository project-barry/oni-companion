#version 440
// Draws one glyph from a signed-distance-field atlas: the quad's 0..1 texture coordinates are mapped
// into the glyph's rectangle of the atlas (uvRect = x, y, w, h in 0..1 atlas coordinates).
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 coord;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 uvRect;
    vec4 color;
    vec4 chan;       // which atlas channel holds the distance: (0,0,0,1) alpha, (1,0,0,0) red
    float spread;    // atlas pixels the 0..1 texture range covers
    float sdfScale;  // screen pixels per atlas pixel
} ubuf;
void main() {
    coord = ubuf.uvRect.xy + qt_MultiTexCoord0 * ubuf.uvRect.zw;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
