# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""Convert an Art object to a list of PolyArea objects.
"""

__author__ = "howard.trickey@gmail.com"

import math
from . import geom
from . import vecfile
import itertools

class ConvertOptions(object):
  """Contains options used to control art to poly conversion.

  Attributes:
    subdiv_kind: int - one of a few 'enum' strings:
	'UNIFORM' - all curves subdivided the same amount
	'ADAPTIVE' - curves subdivided until flat enough
	'EVEN' - curves subdivided to make segments of uniform length
    smoothness: int - controls smoothness of curve conversion:
      usage depends on subdiv_kind:
        'UNIFORM': number of times to subdivide
	'ADAPTIVE': if subdivide a quarter circle bezier this many times,
	  then that is the definition of 'flat enough'
	'EVEN': proportional to 1/uniform-length-of-segments
	  (so higher numbers mean shorter segments)

    filled_only: bool - look only at filled faces
    combine_paths: bool - use union of all subpaths to find
      boundaries and holes instead of just looking for compound
      paths in the input file
    ignore_white: bool - ignore white-filled paths (background, probably)
  """

  def __init__(self):
    self.subdiv_kind = "UNIFORM"
    self.smoothness = 1
    self.filled_only = True
    self.combine_paths = False
    self.ignore_white = True


def ArtToPolyAreas(art, options):
  """Convert Art object to PolyAreas.

  Each filled Path in the Art object will produce zero
  or more PolyAreas.  If options.filled_only is False, then stroked paths
  produce PolyAreas too.

  If options.ignore_white is True, we assume that white is the background
  color and not intended to produce polyareas (for example, sometimes there
  is a filled background rectangle for the entire page).

  If options.combine_paths is True, use the union of all subpaths of all Paths
  to look for outer boundaries and holes, else just look insdie each Path
  separately.

  Args:
    art: vecfile.Art - contains Paths to convert
    options: ConvertOptions
  Returns:
    list of geom.PolyArea
  """

  paths_to_convert = art.paths
  if options.filled_only:
    paths_to_convert = [ p for p in paths_to_convert if p.filled ]
  if options.ignore_white:
    paths_to_convert = [ p for p in paths_to_convert \
                         if p.fillpaint != vecfile.white_paint ]
  # TODO: look for dup paths (both filled and stroked) and dedup
  # TODO (perhaps): look for a 'background rectangle' and remove
  if options.subdiv_kind == "EVEN":
    _SetEvenLength(options, paths_to_convert)
  if options.combine_paths:
    combinedpath = vecfile.Path()
    combinedpath.subpaths = _flatten([ p.subpaths for p in paths_to_convert ])
    return PathToPolyAreas(combinedpath, options)
  else:
    return _flatten([ PathToPolyAreas(p, options) for p in paths_to_convert ])


def PathToPolyAreas(path, options):
  """Convert Path object to PolyAreas.

  Like ArtToPolyAreas, but for a single Path in Art.

  Usually only one PolyArea will be in the returned list,
  but there may be zero if the path has zero area,
  and there may be more than one if it contains
  non-overlapping polygons.
  (TODO: or if it self-crosses)

  Args:
    path: vecfile.Path - the path to convert
    options: ConvertOptions
  Returns:
    list of geom.PolyArea
  """

  subpolyareas = [ _SubpathToPolyArea(sp, options, path.fillpaint.color) \
      for sp in path.subpaths ]
  return CombineSimplePolyAreas(subpolyareas)


def CombineSimplePolyAreas(subpolyareas):
  """Combine PolyAreas without holes into ones that may have holes.

  Take the poly's in each argument PolyArea and find those that
  are contained in others, so returning a list of PolyAreas that may
  contain holes.
  The argument PolyAreas may be reused an modified in forming
  the result.

  Args:
    subpolyareas: list of geom.PolyArea
  Returns:
    list of geom.PolyArea
  """

  n = len(subpolyareas)
  areas = [ geom.SignedArea(pa.poly, pa.points) for pa in subpolyareas ]
  lens = list(map(lambda x: len(x.poly), subpolyareas))
  cls = dict()
  for i in range(n):
    for j in range(n):
      cls[(i, j)] = _ClassifyPathPairs(subpolyareas[i], subpolyareas[j])
  # calculate set cont where (i,j) is in cont if
  # subpolyareas[i] contains subpolyareas[j]
  cont = set()
  for i in range(n):
    for j in range(n):
      if i != j and _Contains(i, j, areas, lens, cls):
        cont.add((i, j))
  # now make real PolyAreas, with holes assigned
  polyareas = []
  assigned = set()
  count = 0
  while len(assigned) < n and count < n:
    for i in range(n):
      if i in assigned:
        continue
      if _IsBoundary(i, n, cont, assigned):
        # have a new boundary area, i
        assigned.add(i)
        holes = _GetHoles(i, n, cont, assigned)
        pa = subpolyareas[i]
        for j in holes:
          pa.AddHole(subpolyareas[j])
        polyareas.append(pa)
    count += 1
  if len(assigned) < n:
    # shouldn't happen
    print("Whoops, PathToPolyAreas didn't assign all")
  return polyareas


def _SubpathToPolyArea(subpath, options, color = (0.0, 0.0, 0.0)):
  """Return a PolyArea representing a single subpath.

  Converts curved segments into approximating line
  segments.
  For 'EVEN' subdiv_kind, divides lines too.
  Ignores zero-length or near zero-length segments.
  Ensures that face is CCW-oriented.

  Args:
    subpath: vecfile.Subpath - the subpath to convert
    options: ConvertOptions
    color: (float, float, float) - rgb of filling color
  Returns:
    geom.PolyArea
  """

  face = []
  prev = None
  ans = geom.PolyArea()
  ans.color = color
  for seg in subpath.segments:
    (ty, start, end) = seg[0:3]
    if not prev or prev != start:
      face.append(start)
    if ty == "L":
      if options.subdiv_kind == "EVEN":
        lines = _EvenLineDivide(start, end, options)
        face.extend(lines[1:])
      else:
        face.append(end)
      prev = end
    elif ty == "B":
      approx = Bezier3Approx([start, seg[3], seg[4], end], options)
      # first point of approx should be current end of face
      face.extend(approx[1:])
      prev = end
    elif ty == "Q":
      print("unimplemented segment type Q")
    else:
      print("unexpected segment type", ty)
  # now make a cleaned face in a new PolyArea
  # with no two successive points approximately equal
  # and a new vmap
  if len(face) <= 2:
    # degenerate face, return an empty PolyArea
    return ans
  previndex = -1
  for i in range(0, len(face)):
    point = face[i]
    newindex = ans.points.AddPoint(point)
    if newindex == previndex or \
        i == len(face)-1 and newindex == ans.poly[0]:
      continue
    ans.poly.append(newindex)
    previndex = newindex
  # make sure that face is CCW oriented
  if geom.SignedArea(ans.poly, ans.points) < 0.0:
    ans.poly.reverse()
  return ans


def Bezier3Approx(cps, options):
  """Compute a polygonal approximation to a cubic bezier segment.

  Args:
    cps: list of 4 coord tuples - (start, control point 1, control point 2, end)
    options: ConvertOptions
  Returns:
    list of tuples (coordinates) for straight line approximation of the bezier
  """

  if options.subdiv_kind == "EVEN":
    return _EvenBezier3Approx(cps, options)
  else:
    return _SubdivideBezier3Approx(cps, options, 0)


def _SetEvenLength(options, paths):
  """Use the bounding box of paths to set even_length in options.

  We want the option.smoothness parameter to control the length
  of segments that we will try to divide Bezier curves into when
  using the EVEN method.  More smoothness -> shorter length.
  But the user should think of this in terms of the overall dimensions
  of their diagram, not in absolute terms.
  Let's say that smoothness==0 means the length should 1/4 the
  size of the longest size of the bounding box, and, for general
  smoothness:

                  longest_side_length
    even_length = -------------------
                  4 * (smoothness+1)

  Args:
    options: ConvertOptions
    paths: list of vecfile.Path
  Side effects:
    Sets options.even_length according to above formula
  """

  minx = 1e10
  maxx = -1e10
  miny = 1e10
  maxy = -1e10
  for p in paths:
    for sp in p.subpaths:
      for seg in sp.segments:
        for (x, y) in seg[1:]:
          minx = min(minx, x)
          maxx = max(maxx, x)
          miny = min(miny, y)
          maxy = max(maxy, y)
  longest_side_length = max(maxx-minx, maxy-miny)
  if longest_side_length <= 0:
    longest_side_length = 1.0
  options.even_length = longest_side_length / (4.0 * (options.smoothness+1))


def _EvenBezier3Approx(cps, options):
  """Use even segment lengths to approximate a cubic bezier segment.

  Args:
    cps: list of 4 coord tuples - (start, control point 1, control point 2, end)
    options: ConvertOptions
  Returns:
    list of tuples (coordinates) for straight line approximation of the bezier
  """

  # This could be made better by recursing a couple of times
  # but the average of the control polygon and chord length is a good
  # first order approximation.
  arc_length = 0.5*(geom.VecLen(geom.VecSub(cps[3], cps[0])) + \
               0.5*(geom.VecLen(geom.VecSub(cps[1], cps[0])) + \
	            geom.VecLen(geom.VecSub(cps[2], cps[1])) + \
	            geom.VecLen(geom.VecSub(cps[3], cps[2]))))
  # make sure segment lengths are at least as short as even_length
  numsegs = math.ceil(arc_length / options.even_length)
  ans = [ cps[0] ]
  for i in range(1, numsegs):
    t = i * (1.0 / numsegs)
    pt = _BezierEval(cps, t)
    ans.append(pt)
  ans.append(cps[3])
  return ans


def _BezierEval(cps, t):
  """Evaluate a cubic Bezier at parameter t.

  Args:
    cps: list of 4 coord tuples - (start, control point 1, control point 2, end)
    t: float - parameter (0 -> start, 1 -> end)
  Returns:
    tuple (coordinates) of point at parameter t along the curve
  """

  b1 = _Bez3step(cps, 1, t)
  b2 = _Bez3step(b1, 2, t)
  b3 = _Bez3step(b2, 3, t)
  return b3[0]

def _EvenLineDivide(start, end, options):
  """Like _EvenBezier3Approx, but for line segments.

  Args:
    start: tuple - coords of start point
    end: tuple - coords of end point
    options: ConvertOptions
  Returns:
    list of tuples (coordinates) for pieces of lines.
  """

  line_length = geom.VecLen(geom.VecSub(end, start))
  numsegs = math.ceil(line_length / options.even_length)
  ans = [ start ]
  for i in range(1, numsegs):
    t = i * (1.0 / numsegs)
    pt = _LinInterp(start, end, t)
    ans.append(pt)
  ans.append(end)
  return ans

def _LinInterp(a, b, t):
  """Return the point that is t of the way from a to b.

  Args:
    a: tuple - coords of start point
    b: tuple - coords of end point
    t: float - interpolation parameter
  Returns:
    tuple (coordinates)
  """

  n = len(a)  # dimension of coordinates
  ans = [ 0.0 ] * n
  for i in range(n):
    ans[i] = (1.0 - t) * a[i] + t * b[i]
  return tuple(ans)


# These ratios chosen so that a 4-bezier approximation
# to a circle gets subdivided 0, 1, 2, etc. times
# when using 'adaptive'.
adaptive_ratios = [ 1.2286, 1.0531, 1.0136, 1.0124, 1.0030, 1.0007 ]

def _SubdivideBezier3Approx(cps, options, recurse_count):
  """Use successive bisection to approximate a cubic bezier segment.

  Args:
    cps: list of 4 coord tuples - (start, control point 1, control point 2, end)
    options: ConvertOptions
    recurse_count: int - how deep have we recursed so far
  Returns:
    list of tuples (coordinates) for straight line approximation of the bezier
  """

  (vs, _, _, ve) = b0 = cps
  subdivide_num = options.smoothness
  adaptive = (options.subdiv_kind == "ADAPTIVE")
  if recurse_count >= subdivide_num and not adaptive:
    return [vs, ve]
  alpha = 0.5
  b1 = _Bez3step(b0, 1, alpha)
  b2 = _Bez3step(b1, 2, alpha)
  b3 = _Bez3step(b2, 3, alpha)
  if adaptive:
    straightlen = geom.VecLen(geom.VecSub(ve, vs))
    if straightlen < geom.DISTTOL:
      return [vs, ve]
    approxcurvelen = \
      geom.VecLen(geom.VecSub(cps[1], cps[0])) + \
      geom.VecLen(geom.VecSub(cps[2], cps[1])) + \
      geom.VecLen(geom.VecSub(cps[3], cps[2]))
    ratio = approxcurvelen / straightlen
    if subdivide_num < 0:
      subdivide_num = 0
    elif subdivide_num >= len(adaptive_ratios):
      subdivide_num = len(adaptive_ratios)-1
    aratio = adaptive_ratios[subdivide_num]
    if ratio <= aratio:
      return [vs, ve]
  else:
    if subdivide_num - recurse_count == 1:
      # recursive case would do this too, but optimize a bit
      return [vs, b3[0], ve]
  left = [b0[0], b1[0], b2[0], b3[0]]
  right = [b3[0], b2[1], b1[2], b0[3]]
  ansleft = _SubdivideBezier3Approx(left, options, recurse_count+1)
  ansright = _SubdivideBezier3Approx(right, options, recurse_count+1)
  # ansleft ends with b3[0] and ansright starts with it
  return ansleft + ansright[1:]


def _Bez3step(b, r, alpha):
  """Cubic bezier step r for interpolating at parameter alpha.

  Steps 1, 2, 3 are applied in succession to the 4 points
  representing a bezier segment, making a triangular arrangement
  of interpolating the previous step's output, so that after
  step 3 we have the point that is at parameter alpha of the segment.
  The left-half control points will be on the left side of the triangle
  and the right-half control points will be on the right side of the triangle.

  Args:
    b: list of tuples (coordinates), of length 5-r
    r: int - step number (0=orig points and cps)
    alpha: float - value in range 0..1 where want to divide at
  Returns:
    list of length 4-r, of vertex coordinates, giving linear interpolations
        at parameter alpha between successive pairs of points in b
  """

  ans = []
  n = len(b[0])  # dimension of coordinates
  beta = 1-alpha
  for i in range(0, 4-r):
    # find c, alpha of the way from b[i] to b[i+1]
    t = [0.0] * n
    for d in range(n):
      t[d] = b[i][d] * beta + b[i+1][d] * alpha
    ans.append(tuple(t))
  return ans


def _ClassifyPathPairs(a, b):
  """Classify vertices of path b with respect to path a.

  Args:
    a: geom.PolyArea - the test outer face (ignoring holes)
    b: geom.PolyArea - the test inner face (ignoring holes)
  Returns:
    (int, int) - first is #verts of b inside a, second is #verts of b on a
  """

  num_in = 0
  num_on = 0
  for v in b.poly:
    vp = b.points.pos[v]
    k = geom.PointInside(vp, a.poly, a.points)
    if k > 0:
      num_in += 1
    elif k == 0:
      num_on += 1
  return (num_in, num_on)


def _Contains(i, j, areas, lens, cls):
  """Return True if path i contains majority of vertices of path j.

  Args:
    i: index of supposed containing path
    j: index of supposed contained path
    areas: list of floats - areas of all the paths
    lens: list of ints - lenths of each of the paths
    cls: dict - maps pairs to result of _ClassifyPathPairs
  Returns:
    bool - True if path i contains at least 55% of j's vertices
  """

  if i == j:
    return False
  (jinsidei, joni) = cls[(i, j)]
  if jinsidei == 0 or joni == lens[j] or \
     float(jinsidei)/float(lens[j]) < 0.55:
    return False
  else:
    (insidej, _) = cls[(j, i)]
    if float(insidej) / float(lens[i]) > 0.55:
      return areas[i] > areas[j]  # tie breaker
    else:
      return True


def _IsBoundary(i, n, cont, assigned):
  """Is path i a boundary, given current assignment?

  Args:
    i: int - index of a path to test for boundary possiblity
    n: int - total number of paths
    cont: dict - maps path pairs (i,j) to _Contains(i,j,...) result
    assigned: set  of int - which paths are already assigned
  Returns:
    bool - True if there is no unassigned j, j!=i, such that
           path j contains path i
  """

  for j in range(0, n):
    if j == i or j in assigned:
      continue
    if (j,i) in cont:
      return False
  return True


def _GetHoles(i, n, cont, assigned):
  """Find holes for path i: i.e., unassigned paths directly inside it.

  Directly inside means there is not some other unassigned path k
  such that path such that path i contains k and path k contains j.
  (If such a k is already assigned, then its islands have been assigned too.)

  Args:
    i: int - index of a boundary path
    n: int - total number of paths
    cont: dict - maps path pairs (i,j) to _Contains(i,j,...) result
    assigned: set  of int - which paths are already assigned
  Returns:
    list of int - indices of paths that are islands
  Side Effect:
    Adds island indices to assigned set.
  """

  isls = []
  for j in range(0, n):
    if j in assigned:
      continue   # catches i==j too, since i is assigned by now
    if (i, j) in cont:
      directly = True
      for k in range(0, n):
        if k == j or k in assigned:
          continue
        if (i, k) in cont and (k, j) in cont:
          directly = False
          break
      if directly:
        isls.append(j)
        assigned.add(j)
  return isls


def _flatten(l):
  """Return a flattened shallow list.

  Args:
    l : list of lists
  Returns:
    list - concatenation of sublists of l
  
  """

  return list(itertools.chain.from_iterable(l))


