"""Creating offset polygons inside faces."""

__author__ = "howard.trickey@gmail.com"

import math
from . import triquad
from .triquad import Sub2, Add2, Angle, Ccw, Normalized2, Perp2, Length2, \
                    LinInterp2, TOL


class Spoke(object):
  """A Spoke is a line growing from an outer vertex to an inner one.

  A Spoke is contained in an Offset (see below).

  Attributes:
    origin: int - index of origin point in an external vmap
    is_reflex: bool - True if spoke grows from a reflex angle
    dir: (float, float) - direction vector (normalized)
    speed: float - at time t, other end of spoke is
        origin + t*dir.  Speed is such that the wavefront
        from the face edges moves at speed 1.
    face: int - index of face containing this Spoke, in Offset
    index: int - index of this Spoke in its face
  """

  def __init__(self, v, prev, next, face, index, vmap):
    """Set attribute of spoke from points making up initial angle.

    The spoke grows from an angle inside a face along the bisector
    of that angle.  Its speed is 1/sin(.5a), where a is the angle
    formed by (prev, v, next).  That speed means that the perpendicular
    from the end of the spoke to either of the prev->v or v->prev
    edges will grow at speed 1.

    Args:
      v: int - index of point spoke grows from
      prev: int - index of point before v on boundary (in CCW order)
      next: int - index of point after v on boundary (in CCW order)
      vmap: list of (float, float) - maps vertex indices to 2d coords
    """

    self.origin = v
    self.face = face
    self.index = index
    vp = vmap[v]
    prevp = vmap[prev]
    nextp = vmap[next]
    uin = Normalized2(Sub2(vp, prevp))
    uout = Normalized2(Sub2(nextp, vp))
    uavg = Normalized2((0.5*(uin[0]+uout[0]), 0.5*(uin[1]+uout[1])))
    # bisector direction is 90 degree CCW rotation of average incoming/outgoing
    self.dir = (-uavg[1], uavg[0])
    self.is_reflex = Ccw(next, v, prev, vmap)
    ang = Angle(prev, v, next, vmap)  # in range [0, 180)
    sin_half_ang = math.sin(math.pi*ang / 360.0)
    if abs(sin_half_ang) < TOL:
      self.speed = 1e7
    else:
      self.speed = 1.0 / sin_half_ang

  def __repr__(self):
    """Printing representation of a Spoke."""

    return "@%d+%gt%s <%d,%d>" % (self.origin, \
            self.speed, str(self.dir), \
            self.face, self.index)

  def EndPoint(self, t, vmap):
    """Return the coordinates of the non-origin point at time t.

    Args:
      t: float - time to find end point
      vmap: list of (float, float) - coordinate map
    Returns:
      (float, float) - coords of spoke's endpoint at time t
    """

    p = vmap[self.origin]
    d = self.dir
    v = self.speed
    return ((p[0]+v*t*d[0], p[1]+v*t*d[1]))

  def VertexEvent(self, other, vmap):
    """Intersect self with other spoke, and return the OffsetEvent, if any.

    A vertex event is with one advancing spoke intersects an adjacent
    adavancing spoke, forming a new vertex.

    Args:
      other: Spoke - other spoke to intersect with
      vmap: list of (float, float) - maps vertex indices to coords
    Returns:
      None or OffsetEvent - if there's an intersection in the growing
        directions of the spokes, will return the OffsetEvent for
        the intersection;
        if lines are collinear or parallel, return None
    """

    a = vmap[self.origin]
    b = Add2(a, self.dir)
    c = vmap[other.origin]
    d = Add2(c, other.dir)
    # find intersection of line ab with line cd
    u = Sub2(b, a)
    v = Sub2(d, c)
    w = Sub2(a, c)
    pp = Perp2(u, v)
    if abs(pp) > TOL:
      # lines or neither parallel nor collinear
      si = Perp2(v, w) / pp
      ti = Perp2(u, w) / pp
      if si >= 0 and ti >= 0:
        p = LinInterp2(a, b, si)
        dist_ab = si*Length2(u)
        dist_cd = ti*Length2(v)
        time_ab = dist_ab / self.speed
        time_cd = dist_cd / other.speed
        time = max(time_ab, time_cd)
        return OffsetEvent(True, time, p, self, other)
    return None

  def EdgeEvent(self, other, offset):
    """Intersect self with advancing edge and return OffsetEvent, if any.

    An edge event is when one advancing spoke intersects an advancing
    edge.  Advancing edges start out as face edges and move perpendicular
    to them, at a rate of 1.  The endpoints of the edge are the advancing
    spokes on either end of the edge (so the edge shrinks or grows as
    it advances). At some time, the edge may shrink to nothing and there
    will be no EdgeEvent after that time.

    We represent an advancing edge by the first spoke (in CCW order
    of face) of the pair of defining spokes.

    At time t, end of this spoke is at
        o + d*s*t
    where o=self.origin, d=self.dir, s= self.speed.
    The advancing edge line has this equation:
        oo + od*os*t + p*a
    where oo, od, os are o, d, s for other spoke, and p is direction
    vector parallel to advancing edge, and a is a real parameter.
    Equating x and y of intersection point:

        o.x + d.x*s*t = oo.x + od.x*os*t + p.x*w
        o.y + d.y*s*t = oo.y + od.y*os*t + p.y*w

    which can be rearranged into the form

        a = bt + cw
        d = et + fw

    and solved for t, w.

    Args:
      other: Spoke - the edge out of this spoke's origin is the advancing
          edge to be checked for intersection
      offset: Offset - the containing Offset
    Returns:
      None or OffsetEvent - with data about the intersection, if any
    """

    vmap = offset.vmap
    o = vmap[self.origin]
    oo = vmap[other.origin]
    otherface = offset.faces[other.face]
    othernext = otherface[(other.index+1) % len(otherface)]
    oonext = vmap[othernext.origin]
    p = Normalized2(Sub2(oonext, oo))
    a = o[0] - oo[0]
    d = o[1] - oo[1]
    b = other.dir[0]*other.speed - self.dir[0]*self.speed
    e = other.dir[1]*other.speed - self.dir[1]*self.speed
    c = p[0]
    f = p[1]
    if abs(c) > TOL:
      dem = e - f*b/c
      if abs(dem) > TOL:
        t = (d - f*a/c) / dem
        w = (a - b*t) / c
      else:
        return None
    elif abs(f) > TOL:
      dem = b - c*e/f
      if abs(dem) > TOL:
        t = (a - c*d/f) / dem
        w = (d - e*t) / f
      else:
        return None
    else:
      return None
    if t < 0.0:
      # intersection is in backward direction along self spoke
      return None
    if w < 0.0:
      # intersection is on wrong side of first end of advancing line segment
      return None
    # calculate the equivalent of w for the other end
    aa = o[0] - oonext[0]
    dd = o[1] - oonext[1]
    bb = othernext.dir[0]*othernext.speed - self.dir[0]*self.speed
    ee = othernext.dir[1]*othernext.speed - self.dir[1]*self.speed
    cc = -p[0]
    ff = -p[1]
    if abs(cc) > TOL:
      ww = (aa - bb*t) / cc
    elif abs(ff) > TOL:
      ww = (dd - ee*t) / ff
    else:
      return None
    if ww < 0.0:
      return None
    evertex = (o[0] + self.dir[0]*self.speed*t, \
               o[1] + self.dir[1]*self.speed*t)
    return OffsetEvent(False, t, evertex, self, other)
    

class OffsetEvent(object):
  """An event involving a spoke during offset computation.

  The events kinds are:
    vertex event: the spoke intersects an adjacent spoke and makes a new vertex
    edge event: the spoke hits an advancing edge and splits it

  Attributes:
    is_vertex_event: True if this is a vertex event (else it is edge event)
    time: float - time at which it happens (edges advance at speed 1)
    event_vertex: (float, float) - intersection point of event
    spoke: Spoke - the spoke that this event is for
    other: Spoke - other spoke involved in event; if vertex event, this will
      be an adjacent spoke that intersects; if an edge event, this is the
      spoke whose origin's outgoing edge grows to hit this event's spoke
  """

  def __init__(self, isv, time, evertex, spoke, other):
    """Creates and initializes attributes of an OffsetEvent."""

    self.is_vertex_event = isv
    self.time = time
    self.event_vertex = evertex
    self.spoke = spoke
    self.other = other

  def __repr__(self):
    """Printing representation of an event."""

    if self.is_vertex_event:
      c = "V"
    else:
      c = "E"
    return "%s t=%5f %s %s %s" % (c, self.time, str(self.event_vertex), \
                                  repr(self.spoke), repr(self.other))


class Offset(object):
  """Represents an offset polygon, and used to construct one.

  Attributes:
    vmap: list of 2-tuples of floats (2d coords)
    faces: list of list of Spoke - each sublist is a closed face
        (oriented CCW); the faces may mutually interfere
    lines: list of (int, int), each representing a line between
        two vertices that are indices into vmap
    points: list of int, each representing a single point
        that is an index into vmap
    endtime: float - time when this offset hits its first
        event (relative to beginning of this offset)
    next: Offset - the offset that takes over after this (inside it)
  """

  def __init__(self, ccwfaces, cwfaces, vmap):
    """Set up initial state of Offset from vertex lists.

    Args:
      ccwfaces: list of list of int - each sublist is a list of indices
          into vmap, giving CCW-oriented faces
      cwfaces: list of list of int - each sublist is a list of indices
          into vmap, giving CW-oriented faces (holes in ccwfaces)
      vmap: list of (float, float) - maps vertex indices to 2d coords
          (may be added to during Offset construction)
    """

    self.vmap = vmap
    self.faces = []
    self.lines = []
    self.points = []
    self.endtime = 1e8
    self.next = None
    findex = 0
    for f in ccwfaces:
      fspokes = []
      nf = len(f)
      if nf == 1:
        self.points.append(f[0])
      elif nf == 2:
        self.lines.append((f[0], f[1]))
      else:
        for i in range(0, nf):
          print("   spoke at vertex", f[i])
          s = Spoke(f[i], f[(i-1) % nf], f[(i+1) % nf], findex, i, vmap)
          fspokes.append(s)
        self.faces.append(fspokes)
        findex += 1
    for f in cwfaces:
      fspokes = []
      nf = len(f)
      for i in range(0, nf):
        print("   spoke at vertex", f[i])
        s = Spoke(f[i], f[(i+1) % nf], f[(i-1) % nf], findex, i, vmap)
        fspokes.append(s)
      self.faces.append(fspokes)
      findex += 1

  def NextSpokeEvents(self, spoke):
    """Return the OffsetEvents that will next happen for a given spoke.

    It might happen that some events happen essentially simultaneously,
    and also it is convenient to separate Edge and Vertex events, so
    we return two lists.
    But, for vertex events, only look at the event with the next Spoke,
    as the event with the previous spoke will be accounted for when we
    consider that previous spoke.

    Args:
      spoke: Spoke - a spoke in one of the faces of this object
    Returns:
      (float, list of OffsetEvent, list of OffsetEvent) - time of next event,
          next Vertex event list and next Edge event list
    """

    face = self.faces[spoke.face]
    nf = len(face)
    bestt = 1e100
    bestv = []
    beste = []
    # First find vertex event (only the one with next spoke)
    next_spoke = face[(spoke.index+1) % nf]
    ev = spoke.VertexEvent(next_spoke, self.vmap)
    if ev:
      bestv = [ev]
      bestt = ev.time
    # Now find edge events, if this is a reflex vertex
    if spoke.is_reflex:
      prev_spoke = face[(spoke.index-1) % nf]
      for f in self.faces:
        nf = len(f)
        for other in f:
          if other == spoke or other == prev_spoke:
            continue
          ev = spoke.EdgeEvent(other, self)
          if ev:
            if ev.time < bestt - TOL:
              beste = []
              bestv = []
              bestt = ev.time
            if abs(ev.time - bestt) < TOL:
              if not beste:
                beste = [ev]
              else:
                pev = beste[-1]
                if ev.spoke != pev.spoke or ev.other.index == (pev.other.index+1)% nf:
                  beste.append(ev)
    return (bestt, bestv, beste)

  def Build(self, target = 2e100):
    """Build the complete Offset structure or up until target time.

    Find the next event(s), makes the appropriate next Offset chained
    from this one, and calls Build on that Offset to continue the
    process until only a single point is left or time reaches target.
    """

    bestt = 1e100
    bestevs = [[], []]
    print("Build", target)
    for f in self.faces:
      for s in f:
        (t, ve, ee) = self.NextSpokeEvents(s)
        print("next spoke events for spoke %s: (%f, %s, %s)" % \
              (str(s), t, str(ve), str(ee)))
        if t < bestt - TOL:
          print("t < bestt - TOL, new bestt=%f" % t)
          bestevs = [[], []]
          bestt = t
        if abs(t-bestt) < TOL:
          print("t ~= bestt, extending")
          bestevs[0].extend(ve)
          bestevs[1].extend(ee)
          print("new best vevs:", str(bestevs[0]))
    self.endtime = bestt
    (ve, ee) = bestevs
    newfaces = []
    if target < self.endtime:
      self.endtime = target
      print("no events, endtime=", self.endtime)
      newfaces.extend(self.MakeNewFaces(self.endtime))
    elif ve and not ee:
      # Only vertex events.
      # Merging of successive vertices in inset face will
      # take care of the vertex events
      print("vertex-only events, endtime=", self.endtime)
      newfaces.extend(self.MakeNewFaces(self.endtime))
    else:
      # Edge events too
      for ev in ee:
        if ev.spoke.face == ev.other.face:
          newfaces.extend(self.MakeNewFaces(self.endtime))
          newfaces = self.SplitFace(newfaces, ev)
        else:
          print("TODO: handle event-crosses-faces edge event")
          newfaces.extend(self.MakeNewFaces(self.endtime))
    nexttarget = target - self.endtime
    anyfaces = False
    for f in newfaces:
      if len(f) >= 3:
        anyfaces = True
        break
    if anyfaces and nexttarget > TOL:
      nextoff = Offset(newfaces, [], self.vmap)
      self.next = nextoff
      self.Build(nexttarget)

  def FaceAtSpokeEnds(self, f, t):
    """Return a new face that is at the spoke ends of face f at time t.

    Also merges any adjacent approximately equal vertices into one vertex,
    so returned list may be smaller than len(f).

    Args:
      f: list of Spoke - one of self.faces
      t: float - time
    Returns:
      list of int - indices into self.vmap (which has been extended)
    """
    newfacevs = []
    for i in range(0, len(f)):
      s = f[i]
      v = s.EndPoint(t, self.vmap)
      if newfacevs:
        if not ApproxEqPts(v, newfacevs[-1]):
          if not (i == len(f)-1 and ApproxEqPts(v, newfacevs[0])):
            newfacevs.append(v)
      else:
        newfacevs.append(v)
    newface = []
    for v in newfacevs:
      self.vmap.append(v)
      newface.append(len(self.vmap)-1)
      print("new vertex %d at (%f,%f)" % (len(self.vmap)-1, v[0], v[1]))
    return newface

  def MakeNewFaces(self, t):
    """For each face in this offset, make new face extending spokes to time t.

    Args:
      t: double - time
    Returns:
      list of list of int - list of new faces
    """

    ans = []
    for f in self.faces:
      newf = self.FaceAtSpokeEnds(f, t)
      ans += newf
    return ans

  def SplitFace(self, newfaces, ev):
    """Use event ev to split its face into two faces.
    
    Assuming ev doesn't cross faces, split the face that is currently
    the dest of ev.spoke into two faces, keeping one at its current
    place in newfaces, and adding the other to the end.

    Args:
      newfaces: list of list of int - the new faces
      ev: OffsetEvent - an edge event
    Returns:
      list of list of int - modified newfaces
    """

    ans = []
    findex = ev.spoke.face
    f = newfaces[findex]
    nf = len(f)
    si = ev.spoke.index
    pi = ev.other.index
    print("split face, si=%d, pi=%d)" % (si, pi))
    newf0 = findex
    newf1 = len(newfaces)
    newface0 = []
    newface1 = []
    # The tow new faces put spoke si's dest on edge between
    # pi's dest and qi (edge after pi)'s dest in original face.
    # These are indices in the original face; the current dest face
    # may have fewer elements because of merging successive points
    return ans


def ApproxEqPts(a, b):
  """Returns true if 2d ponts a and b are the same, within tolerance.

  Args:
    a: (float, float) - first point
    b: (float, float) - second point
  Returns:
    bool - True if both coords are closer than TOL
  """

  (xa, ya) = a
  (xb, yb) = b
  return abs(xa-xb) < TOL and abs(ya-yb) < TOL


