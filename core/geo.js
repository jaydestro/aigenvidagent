// Shared geometry helpers: orthographic globe (d3-geo + Natural Earth 110m land), isometric projection, SVG builders.
import { geoOrthographic, geoPath, geoGraticule10, geoNaturalEarth1, geoEquirectangular, geoCircle } from 'd3-geo';
import { feature } from 'topojson-client';
import land110 from 'world-atlas/land-110m.json';

export const LAND = feature(land110, land110.objects.land);
export const GRAT = geoGraticule10();
export { geoNaturalEarth1, geoEquirectangular, geoPath, geoOrthographic, geoCircle };

export const NS = 'http://www.w3.org/2000/svg';
export function svgEl(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
export function htmlEl(tag, attrs = {}, parent, html) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (html != null) e.innerHTML = html;
  if (parent) parent.appendChild(e);
  return e;
}

// Orthographic globe drawn into an SVG <g>. Returns update(lon, lat, r).
export function orthoGlobe(g, { cx, cy, r, landClass = 'land', gratClass = 'grat', rimClass = 'rim' }) {
  const proj = geoOrthographic().translate([cx, cy]).scale(r).clipAngle(90).precision(0.4);
  const path = geoPath(proj);
  const rim = svgEl('circle', { cx, cy, r, class: rimClass }, g);
  const grat = svgEl('path', { class: gratClass }, g);
  const land = svgEl('path', { class: landClass }, g);
  return {
    proj,
    path,
    update(lon, lat = -12, rr = r, ccx = cx, ccy = cy) {
      proj.rotate([lon, lat]).scale(rr).translate([ccx, ccy]);
      rim.setAttribute('r', rr); rim.setAttribute('cx', ccx); rim.setAttribute('cy', ccy);
      grat.setAttribute('d', path(GRAT));
      land.setAttribute('d', path(LAND));
    },
    point(lon, lat) {
      const p = proj([lon, lat]);
      const r = proj.rotate();
      // visible if angular distance from centre < 90
      const toRad = Math.PI / 180;
      const c = Math.sin(-r[1] * toRad) * Math.sin(lat * toRad) + Math.cos(-r[1] * toRad) * Math.cos(lat * toRad) * Math.cos((lon + r[0]) * toRad);
      return { x: p[0], y: p[1], vis: c > 0.05, depth: c };
    },
  };
}

// Isometric projection: x to the right-down, y to the left-down, z up.
export function isoFactory(ox, oy, k) {
  const c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6);
  return (x, y, z = 0) => [ox + (x - y) * c * k, oy + (x + y) * s * k - z * k];
}
export const ptsToD = (pts, close = true) => 'M' + pts.map((p) => p.map((v) => v.toFixed(1)).join(',')).join('L') + (close ? 'Z' : '');

// Isometric box: returns {top, left, right} path data (visible faces from the default iso view).
export function isoBox(iso, x, y, z, w, d, h) {
  const P = (a, b, c) => iso(a, b, c);
  return {
    top: ptsToD([P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)]),
    right: ptsToD([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)]),
    left: ptsToD([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)]),
  };
}

// Deterministic pseudo-random
export function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
