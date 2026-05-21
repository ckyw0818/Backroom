import random

from direct.filter.FilterManager import FilterManager
from direct.showbase import ShowBaseGlobal
from panda3d.core import Shader, Texture, ClockObject


vshader = """
#version 130

uniform mat4 p3d_ModelViewProjectionMatrix;

in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;

out vec2 uv;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv = p3d_MultiTexCoord0;
}
"""


bright_fshader = """
#version 130

uniform sampler2D tex;
uniform float threshold;
uniform float soft;

in vec2 uv;
out vec4 fragColor;

void main() {
    vec3 c = texture(tex, uv).rgb;
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    float m = smoothstep(threshold - soft, threshold + soft, l);

    fragColor = vec4(c * m, 1.0);
}
"""


blur_fshader = """
#version 130

uniform sampler2D tex;
uniform vec2 dir;
uniform float radius;

in vec2 uv;
out vec4 fragColor;

vec3 sample_tex(vec2 p) {
    return texture(tex, clamp(p, vec2(0.0), vec2(1.0))).rgb;
}

void main() {
    vec2 px = dir * radius / vec2(textureSize(tex, 0));

    vec3 c = vec3(0.0);

    c += sample_tex(uv + px * -6.0) * 0.00443;
    c += sample_tex(uv + px * -5.0) * 0.01622;
    c += sample_tex(uv + px * -4.0) * 0.04677;
    c += sample_tex(uv + px * -3.0) * 0.10598;
    c += sample_tex(uv + px * -2.0) * 0.18845;
    c += sample_tex(uv + px * -1.0) * 0.26372;
    c += sample_tex(uv)             * 0.29716;
    c += sample_tex(uv + px *  1.0) * 0.26372;
    c += sample_tex(uv + px *  2.0) * 0.18845;
    c += sample_tex(uv + px *  3.0) * 0.10598;
    c += sample_tex(uv + px *  4.0) * 0.04677;
    c += sample_tex(uv + px *  5.0) * 0.01622;
    c += sample_tex(uv + px *  6.0) * 0.00443;

    c /= 1.5473;

    fragColor = vec4(c, 1.0);
}
"""


final_fshader = """
#version 130

uniform sampler2D tex;
uniform sampler2D bloom_tex;

uniform float blur;
uniform float sharp;

uniform float lens_k;
uniform float lens_zoom;

uniform float bloom_strength;
uniform float exposure;

uniform vec2 pix_a;
uniform vec2 pix_b;
uniform vec2 pix_c;
uniform vec2 pix_d;
uniform vec2 pix_e;

uniform float pix_a_opacity;
uniform float pix_b_opacity;
uniform float pix_c_opacity;
uniform float pix_d_opacity;
uniform float pix_e_opacity;

uniform float posterize_levels;

uniform float time;
uniform float line_noise_strength;
uniform float line_noise_density;
uniform float line_noise_rows;
uniform float line_noise_thickness;
uniform float line_noise_min_len;
uniform float line_noise_max_len;
uniform float line_noise_speed;

in vec2 uv;
out vec4 fragColor;

float hash1(float n) {
    return fract(sin(n) * 43758.5453123);
}

vec2 lens(vec2 p) {
    vec2 q = p - 0.5;
    float r2 = dot(q, q);

    q *= 1.0 + lens_k * r2;
    q *= lens_zoom;

    return q + 0.5;
}

vec3 sample_tex(sampler2D tex0, vec2 p) {
    return texture(tex0, clamp(p, vec2(0.0), vec2(1.0))).rgb;
}

vec3 blur9(sampler2D tex0, vec2 p, float r) {
    vec2 px = r / vec2(textureSize(tex0, 0));

    vec3 c = vec3(0.0);

    c += sample_tex(tex0, p + px * vec2(-1.0, -1.0)) * 1.0;
    c += sample_tex(tex0, p + px * vec2( 0.0, -1.0)) * 2.0;
    c += sample_tex(tex0, p + px * vec2( 1.0, -1.0)) * 1.0;

    c += sample_tex(tex0, p + px * vec2(-1.0,  0.0)) * 2.0;
    c += sample_tex(tex0, p + px * vec2( 0.0,  0.0)) * 4.0;
    c += sample_tex(tex0, p + px * vec2( 1.0,  0.0)) * 2.0;

    c += sample_tex(tex0, p + px * vec2(-1.0,  1.0)) * 1.0;
    c += sample_tex(tex0, p + px * vec2( 0.0,  1.0)) * 2.0;
    c += sample_tex(tex0, p + px * vec2( 1.0,  1.0)) * 1.0;

    return c / 16.0;
}

vec3 process(vec2 p) {
    vec3 b1 = blur9(tex, p, blur * 2.4);
    vec3 b2 = blur9(tex, p, blur * 6.0);

    vec3 c = b1 + (b1 - b2) * sharp;

    vec3 bl = sample_tex(bloom_tex, p);
    c += bl * bloom_strength;

    c = vec3(1.0) - exp(-c * exposure);
    c = clamp(c, 0.0, 1.0);

    return c;
}

vec2 pix_uv(vec2 p, vec2 block_size) {
    vec2 s = vec2(textureSize(tex, 0));
    vec2 bs = max(block_size, vec2(1.0));
    vec2 q = floor(p * s / bs) * bs + bs * 0.5;
    return q / s;
}

vec3 posterize(vec3 c, float levels) {
    levels = max(levels, 2.0);
    return floor(c * levels) / levels;
}

float horizontal_line_noise(vec2 p) {
    float tt = floor(time * line_noise_speed);

    float y = p.y * line_noise_rows;
    float row = floor(y);
    float fy = fract(y) - 0.5;

    float r0 = hash1(row * 17.31 + tt * 0.37);
    float onoff = step(r0, line_noise_density);

    float thick = clamp(line_noise_thickness, 0.02, 0.98);
    float row_mask = 1.0 - smoothstep(thick, thick + 0.08, abs(fy));

    float start = hash1(row * 3.17 + tt * 0.11) * 0.82;
    float len_r = hash1(row * 5.91 + tt * 0.19);
    float len = mix(line_noise_min_len, line_noise_max_len, len_r);
    float endp = min(start + len, 0.98);

    float edge = 0.01;
    float xm1 = smoothstep(start - edge, start + edge, p.x);
    float xm2 = 1.0 - smoothstep(endp - edge, endp + edge, p.x);
    float xmask = xm1 * xm2;

    float inten = mix(0.65, 1.0, hash1(row * 9.73 + tt * 0.23));

    return onoff * row_mask * xmask * inten;
}
void main() {
    vec2 p = lens(uv);

    vec3 c = process(p);

    float ln = horizontal_line_noise(p);
    c += vec3(ln) * line_noise_strength;
    c = clamp(c, 0.0, 1.0);

    vec3 pa = process(pix_uv(p, pix_a));
    vec3 pb = process(pix_uv(p, pix_b));
    vec3 pc = process(pix_uv(p, pix_c));
    vec3 pd = process(pix_uv(p, pix_d));
    vec3 pe = process(pix_uv(p, pix_e));

    c = mix(c, pa, pix_a_opacity);
    c = mix(c, pb, pix_b_opacity);
    c = mix(c, pc, pix_c_opacity);
    c = mix(c, pd, pix_d_opacity);
    c = mix(c, pe, pix_e_opacity);

    c = posterize(c, posterize_levels);
    c = clamp(c, 0.0, 1.0);

    fragColor = vec4(c, 1.0);
}
"""


class PostEffects:
    def __init__(
        self,
        blur=1.6,
        sharp=2.2,
        lens_k=-0.18,
        lens_zoom=1.03,
        bloom_threshold=0.62,
        bloom_soft=0.18,
        bloom_radius=5.5,
        bloom_strength=0.38,
        exposure=1.0,

        pix_a_range=((80.0, 180.0), (220.0, 520.0)),
        pix_b_range=((8.0, 20.0), (50.0, 120.0)),
        pix_c_range=((20.0, 55.0), (12.0, 35.0)),
        pix_d_range=((2.0, 8.0), (14.0, 35.0)),
        pix_e_range=((4.0, 12.0), (3.0, 9.0)),

        pix_a_opacity=0.06,
        pix_b_opacity=0.10,
        pix_c_opacity=0.16,
        pix_d_opacity=0.22,
        pix_e_opacity=0.30,

        posterize_levels=128.0,

        line_noise_strength=0.18,
        line_noise_density=0.02,
        line_noise_rows=320.0,
        line_noise_thickness=0.08,
        line_noise_min_len=0.18,
        line_noise_max_len=0.75,
        line_noise_speed=24.0,

        jitter_speed=1,
        div=4
    ):
        self.blur = blur
        self.sharp = sharp

        self.lens_k = lens_k
        self.lens_zoom = lens_zoom

        self.bloom_threshold = bloom_threshold
        self.bloom_soft = bloom_soft
        self.bloom_radius = bloom_radius
        self.bloom_strength = bloom_strength
        self.exposure = exposure

        self.pix_a_range = pix_a_range
        self.pix_b_range = pix_b_range
        self.pix_c_range = pix_c_range
        self.pix_d_range = pix_d_range
        self.pix_e_range = pix_e_range

        self.pix_a = (125.0, 420.0)
        self.pix_b = (10.0, 75.0)
        self.pix_c = (30.0, 20.0)
        self.pix_d = (4.0, 25.0)
        self.pix_e = (6.0, 4.0)

        self.pix_a_opacity = pix_a_opacity
        self.pix_b_opacity = pix_b_opacity
        self.pix_c_opacity = pix_c_opacity
        self.pix_d_opacity = pix_d_opacity
        self.pix_e_opacity = pix_e_opacity

        self.posterize_levels = posterize_levels

        self.line_noise_strength = line_noise_strength
        self.line_noise_density = line_noise_density
        self.line_noise_rows = line_noise_rows
        self.line_noise_thickness = line_noise_thickness
        self.line_noise_min_len = line_noise_min_len
        self.line_noise_max_len = line_noise_max_len
        self.line_noise_speed = line_noise_speed

        self.jitter_speed = jitter_speed
        self.frame = 0

        self.scene_tex = Texture()
        self.bright_tex = Texture()
        self.blur_a_tex = Texture()
        self.blur_b_tex = Texture()

        self.manager = FilterManager(ShowBaseGlobal.base.win, ShowBaseGlobal.base.cam)

        self.final_quad = self.manager.renderSceneInto(colortex=self.scene_tex)
        self.bright_quad = self.manager.renderQuadInto(colortex=self.bright_tex, div=div)
        self.blur_a_quad = self.manager.renderQuadInto(colortex=self.blur_a_tex, div=div)
        self.blur_b_quad = self.manager.renderQuadInto(colortex=self.blur_b_tex, div=div)

        self.bright_shader = Shader.make(Shader.SL_GLSL, vshader, bright_fshader)
        self.blur_shader = Shader.make(Shader.SL_GLSL, vshader, blur_fshader)
        self.final_shader = Shader.make(Shader.SL_GLSL, vshader, final_fshader)

        self.bright_quad.setShader(self.bright_shader)
        self.bright_quad.setShaderInput('tex', self.scene_tex)
        self.bright_quad.setShaderInput('threshold', self.bloom_threshold)
        self.bright_quad.setShaderInput('soft', self.bloom_soft)

        self.blur_a_quad.setShader(self.blur_shader)
        self.blur_a_quad.setShaderInput('tex', self.bright_tex)
        self.blur_a_quad.setShaderInput('dir', (1.0, 0.0))
        self.blur_a_quad.setShaderInput('radius', self.bloom_radius)

        self.blur_b_quad.setShader(self.blur_shader)
        self.blur_b_quad.setShaderInput('tex', self.blur_a_tex)
        self.blur_b_quad.setShaderInput('dir', (0.0, 1.0))
        self.blur_b_quad.setShaderInput('radius', self.bloom_radius)

        self.final_quad.setShader(self.final_shader)
        self.final_quad.setShaderInput('tex', self.scene_tex)
        self.final_quad.setShaderInput('bloom_tex', self.blur_b_tex)

        self.randomize_pixelize()
        self.set_inputs()

    def rand_pix(self, r):
        x = random.uniform(r[0][0], r[0][1])
        y = random.uniform(r[1][0], r[1][1])
        return (x, y)

    def randomize_pixelize(self):
        self.pix_a = self.rand_pix(self.pix_a_range)
        self.pix_b = self.rand_pix(self.pix_b_range)
        self.pix_c = self.rand_pix(self.pix_c_range)
        self.pix_d = self.rand_pix(self.pix_d_range)
        self.pix_e = self.rand_pix(self.pix_e_range)

    def set_inputs(self):
        self.bright_quad.setShaderInput('threshold', self.bloom_threshold)
        self.bright_quad.setShaderInput('soft', self.bloom_soft)

        self.blur_a_quad.setShaderInput('radius', self.bloom_radius)
        self.blur_b_quad.setShaderInput('radius', self.bloom_radius)

        self.final_quad.setShaderInput('blur', self.blur)
        self.final_quad.setShaderInput('sharp', self.sharp)
        self.final_quad.setShaderInput('lens_k', self.lens_k)
        self.final_quad.setShaderInput('lens_zoom', self.lens_zoom)
        self.final_quad.setShaderInput('bloom_strength', self.bloom_strength)
        self.final_quad.setShaderInput('exposure', self.exposure)

        self.final_quad.setShaderInput('pix_a', self.pix_a)
        self.final_quad.setShaderInput('pix_b', self.pix_b)
        self.final_quad.setShaderInput('pix_c', self.pix_c)
        self.final_quad.setShaderInput('pix_d', self.pix_d)
        self.final_quad.setShaderInput('pix_e', self.pix_e)

        self.final_quad.setShaderInput('pix_a_opacity', self.pix_a_opacity)
        self.final_quad.setShaderInput('pix_b_opacity', self.pix_b_opacity)
        self.final_quad.setShaderInput('pix_c_opacity', self.pix_c_opacity)
        self.final_quad.setShaderInput('pix_d_opacity', self.pix_d_opacity)
        self.final_quad.setShaderInput('pix_e_opacity', self.pix_e_opacity)

        self.final_quad.setShaderInput('posterize_levels', self.posterize_levels)

        self.final_quad.setShaderInput('line_noise_strength', self.line_noise_strength)
        self.final_quad.setShaderInput('line_noise_density', self.line_noise_density)
        self.final_quad.setShaderInput('line_noise_rows', self.line_noise_rows)
        self.final_quad.setShaderInput('line_noise_thickness', self.line_noise_thickness)
        self.final_quad.setShaderInput('line_noise_min_len', self.line_noise_min_len)
        self.final_quad.setShaderInput('line_noise_max_len', self.line_noise_max_len)
        self.final_quad.setShaderInput('line_noise_speed', self.line_noise_speed)

        tm = ClockObject.getGlobalClock().getFrameTime()
        self.final_quad.setShaderInput('time', tm)

    def update(self):
        self.frame += 1

        if self.frame % self.jitter_speed == 0:
            self.randomize_pixelize()

        self.set_inputs()

    def flicker(self):
        pass

    def calm(self):
        pass