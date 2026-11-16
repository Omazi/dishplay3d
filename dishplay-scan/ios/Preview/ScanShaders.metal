#include <metal_stdlib>
using namespace metal;

struct Uniforms {
    float4x4 viewProj;
    float3 lightDir;
    float pointSize;
    uint showMesh;
};

struct PointOut {
    float4 position [[position]];
    float4 color;
    float size [[point_size]];
};

// Points: positions (packed float3, object frame, metres) + rgb/class bytes. One GPU buffer, no entity per point.
vertex PointOut pointVertex(uint vid [[vertex_id]],
                            const device packed_float3 *pos [[buffer(0)]],
                            const device uchar4 *rgbc [[buffer(1)]],
                            constant Uniforms &u [[buffer(2)]]) {
    PointOut o;
    o.position = u.viewProj * float4(float3(pos[vid]), 1.0);
    uchar4 c = rgbc[vid];
    float3 rgb = float3(c.rgb) / 255.0;
    uint cls = c.a;
    float alpha = 1.0;
    float size = u.pointSize;
    if (cls == 4) { rgb = mix(rgb, float3(0.55), 0.35); alpha = 0.75; }            // provisional single view
    if (cls == 3) { rgb = float3(0.75, 0.75, 0.80); alpha = 0.6; size *= 0.7; }     // ARKit tracking points
    if (u.showMesh != 0 && cls == 0) { size *= 0.6; }
    o.color = float4(rgb, alpha);
    o.size = size;
    return o;
}

fragment float4 pointFragment(PointOut in [[stage_in]], float2 pc [[point_coord]]) {
    if (length(pc - 0.5) > 0.5) discard_fragment();
    return in.color;
}

struct MeshOut {
    float4 position [[position]];
    float3 color;
    float3 normal;
    float cls;
};

vertex MeshOut meshVertex(uint vid [[vertex_id]],
                          const device packed_float3 *pos [[buffer(0)]],
                          const device uchar4 *rgbc [[buffer(1)]],
                          const device char4 *nrm [[buffer(2)]],
                          constant Uniforms &u [[buffer(3)]]) {
    MeshOut o;
    o.position = u.viewProj * float4(float3(pos[vid]), 1.0);
    uchar4 c = rgbc[vid];
    o.color = float3(c.rgb) / 255.0;
    o.normal = float3(nrm[vid].xyz) / 127.0;
    o.cls = float(c.a);
    return o;
}

fragment float4 meshFragment(MeshOut in [[stage_in]], constant Uniforms &u [[buffer(0)]]) {
    float3 n = normalize(in.normal);
    float shade = 0.45 + 0.55 * abs(dot(n, normalize(u.lightDir)));
    float3 rgb = in.color * shade;
    if (in.cls > 0.5 && in.cls < 1.5) {          // interpolated by fusion: visibly tinted
        rgb = mix(rgb, float3(0.25, 0.45, 0.95), 0.45);
    } else if (in.cls > 1.5 && in.cls < 2.5) {   // estimated (completion): magenta stripes
        float s = step(0.5, fract((in.position.x + in.position.y) * 0.08));
        rgb = mix(rgb, float3(0.9, 0.2, 0.8), 0.4 + 0.3 * s);
    }
    return float4(rgb, 1.0);
}
