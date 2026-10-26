"""Reduce SAM contours only when raster and boundary checks preserve the shape."""
from __future__ import annotations
import cv2
import numpy as np


def _simple(poly):
    # A closed ring may not cross itself or collapse onto a nonadjacent edge.
    def cross(a,b,c):
        u,v=b-a,c-a
        return float(u[0]*v[1]-u[1]*v[0])
    n=len(poly)
    for i in range(n):
        a,b=poly[i],poly[(i+1)%n]
        for j in range(i+2,n):
            if i==0 and j==n-1:continue
            c,d=poly[j],poly[(j+1)%n]
            if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]) or max(a[1],b[1])<min(c[1],d[1]) or max(c[1],d[1])<min(a[1],b[1]):continue
            if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0:return False
    return True


def simplify_ring(points, epsilon=1.0):
    arr=np.asarray(points,dtype=np.float32).reshape(-1,2)
    if len(arr)<4:return arr.tolist()
    origin=np.floor(arr.min(axis=0)).astype(int)-4
    size=np.ceil(arr.max(axis=0)-origin).astype(int)+5
    if int(size[0])*int(size[1])>16000000:return arr.tolist()
    raw=np.zeros((size[1],size[0]),np.uint8)
    cv2.fillPoly(raw,[np.rint(arr-origin).astype(np.int32)],1)
    area=int(raw.sum())
    if area==0:return arr.tolist()
    kernel=np.ones((3,3),np.uint8)
    boundary=raw-cv2.erode(raw,kernel)
    distance=cv2.distanceTransform(1-boundary,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    interior=cv2.distanceTransform(raw,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    # Local maxima of the distance field protect narrow branches and endpoints.
    ridge=(interior>0)&(interior<=4)&(interior>=cv2.dilate(interior,kernel)-1e-5)
    protected=cv2.dilate(ridge.astype(np.uint8),np.ones((9,9),np.uint8)).astype(bool)
    candidates=[]
    limit=min(3.,max(.125,float(epsilon)*3))
    for value in np.arange(.125,limit+.01,.125):
        reduced=cv2.approxPolyDP(arr,value,True).reshape(-1,2)
        if len(reduced)<3:continue
        candidates.append((len(reduced),float(value),reduced))
    checked=set()
    for _,value,reduced in sorted(candidates,key=lambda t:(t[0],t[1])):
        key=reduced.tobytes()
        if key in checked:continue
        checked.add(key)
        if not _simple(reduced):continue
        trial=np.zeros_like(raw)
        cv2.fillPoly(trial,[np.rint(reduced-origin).astype(np.int32)],1)
        union=np.count_nonzero(raw|trial)
        if np.count_nonzero(raw&trial)/max(1,union)<.99:continue
        if abs(int(trial.sum())-area)/area>.01:continue
        edge=trial-cv2.erode(trial,kernel)
        reverse=cv2.distanceTransform(1-edge,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        errors=np.concatenate((distance[edge>0],reverse[boundary>0]))
        if errors.max(initial=0)>min(3.,limit) or np.percentile(errors,95)>min(1.5,limit):continue
        if np.any(protected):
            a=raw[protected];b=trial[protected]
            if np.count_nonzero(a&b)/max(1,np.count_nonzero(a|b))<.98:continue
            if abs(int(a.sum())-int(b.sum()))/max(1,int(a.sum()))>.02:continue
        return reduced.tolist()
    return arr.tolist()
