// Millimeter coordinates; geometry example, not a calibrated fit specification.
/* [Plate] */
width = 40;          // [20:1:120]
depth = 24;          // [20:1:100]
thickness = 4;       // [1:0.5:12]
/* [Holes] */
hole_diameter = 4;   // [1:0.5:12]
inset = 6;           // Center distance from each neighboring outer edge.
/* [Hidden] */
$fn = 0;
$fa = 4;
$fs = 0.2;
epsilon = min(0.01, thickness / 100);

assert(width > 0 && depth > 0 && thickness > 0 && hole_diameter > 0,
       "Dimensions must be positive");
assert(inset > hole_diameter / 2, "Holes must stay inside the plate");
assert(min(width, depth) > 2 * inset + hole_diameter,
       "Opposite holes must stay separate");

echo(extents_mm = [width, depth, thickness], hole_diameter_mm = hole_diameter);
echo(hole_centers_mm = [for (x = [inset, width - inset])
                           for (y = [inset, depth - inset]) [x, y]]);

difference() {
    cube([width, depth, thickness], center = false);
    for (x = [inset, width - inset])
        for (y = [inset, depth - inset])
            translate([x, y, -epsilon])
                cylinder(d = hole_diameter, h = thickness + 2 * epsilon,
                         center = false);
}
