"""Ruled-cell detection. Text alignment alone is never evidence of a table."""
from math import atan2, degrees
from statistics import median
import cv2
import numpy as np
from PIL import Image


def _ruled_cells(image):
    rgb=np.asarray(image.convert('RGB'))
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    h,w=gray.shape
    edges=cv2.Canny(gray,40,120)
    min_length=max(18,round(min(w,h)*.018))
    lines=cv2.HoughLinesP(edges,1,np.pi/720,threshold=max(18,min_length//2),minLineLength=min_length,maxLineGap=max(3,min_length//5))
    if lines is None:return image,[]
    angles=[]
    for x1,y1,x2,y2 in lines[:,0]:
        angle=degrees(atan2(y2-y1,x2-x1))
        if abs(x2-x1)>w*.25 and abs(angle)<3:angles.append(angle)
    angle=median(angles) if angles else 0
    if abs(angle)>.08:
        matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
        rgb=cv2.warpAffine(rgb,matrix,(w,h),borderValue=(255,255,255))
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        edges=cv2.Canny(gray,40,120)
        lines=cv2.HoughLinesP(edges,1,np.pi/720,threshold=max(18,min_length//2),minLineLength=min_length,maxLineGap=max(3,min_length//5))
        aligned=Image.fromarray(rgb)
        aligned.info["ocr_layout_transform"]=matrix.tolist()
    else:aligned=image
    if lines is None:return aligned,[]
    # Long horizontal rules locate table bands. Character strokes cannot define
    # a column unless they connect the top and bottom rules of a row.
    ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,15,10)
    edge_mask=cv2.dilate(ink,np.ones((3,1),np.uint8))
    horizontal=cv2.morphologyEx(edge_mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(30,w//5),1)))
    horizontal=cv2.morphologyEx(horizontal,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(12,1)))
    contours,_=cv2.findContours(horizontal,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    rules=[]
    for c in contours:
        x,y,cw,ch=cv2.boundingRect(c)
        if cw>w*.2 and ch<max(20,h*.015):rules.append((x,y+ch/2,x+cw))
    groups=[]
    for rule in sorted(rules,key=lambda r:r[1]):
        group=next((g for g in groups if abs(median(r[0] for r in g)-rule[0])<w*.06 and abs(median(r[2] for r in g)-rule[2])<w*.06 and rule[1]-g[-1][1]<max(h*.4,w*.15)),None)
        if group is None:groups.append([rule])
        else:group.append(rule)
    def snap(values,tolerance=6):
        result=[]
        for value in sorted(values):
            if result and value-result[-1][-1]<=tolerance:result[-1].append(value)
            else:result.append([value])
        return [round(median(g)) for g in result]
    regions=[]
    for rules in groups:
        if len(rules)<3:continue
        left=round(median(r[0] for r in rules));right=round(median(r[2] for r in rules))
        ys=snap([r[1] for r in rules],max(4,min_length*.15))
        bands=[]
        strong_boundaries={}
        for top,bottom in zip(ys,ys[1:]):
            rh=bottom-top
            if rh<10:continue
            crop=ink[max(0,top-3):min(h,bottom+4),max(0,left-6):min(w,right+7)]
            vertical=cv2.morphologyEx(cv2.dilate(crop,np.ones((1,3),np.uint8)),cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(8,round(rh*.75)))))
            counts=(vertical>0).sum(axis=0)
            xs=snap([left-6+int(x) for x in np.where(counts>rh*.75)[0]],max(4,min_length*.15))
            strong_boundaries[top,bottom]=snap([left-6+int(x) for x in np.where(counts>rh*.96)[0]],max(4,min_length*.15))
            xs=[x for x in xs if left-12<=x<=right+12]
            if len(xs)>=2 and xs[-1]-xs[0]>(right-left)*.85:
                bands.append((top,bottom,xs))
            else:bands.append(None)
        # Split at gaps without vertical side borders (page headers/underlines).
        runs=[]
        for band in bands:
            if band is None:
                if runs and runs[-1]:runs.append([])
            else:
                if not runs:runs.append([])
                runs[-1].append(band)
        for run in runs:
            if len(run)<2:continue
            anchors=snap([x for _,_,xs in run for x in xs],max(6,min_length*.3))
            # A new interior column must recur; this rejects tall handwritten
            # strokes that touch one row's borders.
            support={x:sum(any(abs(x-v)<=max(6,min_length*.3) for v in xs) for _,_,xs in run) for x in anchors}
            def strong_at(x,top,bottom):
                return any(abs(x-v)<=max(6,min_length*.3) for v in strong_boundaries.get((top,bottom),[]))
            anchors=[x for i,x in enumerate(anchors) if i in (0,len(anchors)-1) or support[x]>=max(2,(len(run)+1)//2) or sum(strong_at(x,top,bottom) for top,bottom,_ in run)>=3 or any(bottom-top>=min_length*2.3 and strong_at(x,top,bottom) for top,bottom,_ in run)]
            if len(anchors)<3 or len(anchors)>41:continue
            cells=[]
            run_ys=[run[0][0]]+[b for _,b,_ in run]
            for ri,(top,bottom,xs) in enumerate(run):
                columns=sorted(set(min(range(len(anchors)),key=lambda c:abs(anchors[c]-v)) for v in xs if min(abs(a-v) for a in anchors)<=max(6,min_length*.4)))
                for a,b in zip(columns,columns[1:]):
                    cells.append({'bbox':(anchors[a],top,anchors[b],bottom),'row':ri,'column':a,'rowspan':1,'colspan':b-a})
            if len(cells)>=3:regions.append({'bbox':(anchors[0],run_ys[0],anchors[-1],run_ys[-1]),'xs':anchors,'ys':run_ys,'cells':cells})
    regions.sort(key=lambda r:r['bbox'][1])
    return aligned,regions


def ruled_cells(image):
    """Use a stable analysis resolution while retaining full-resolution OCR crops."""
    width,height=image.size
    scale=min(1.0,1670/min(width,height))
    if scale==1:return _ruled_cells(image)
    small=image.resize((round(width*scale),round(height*scale)),Image.Resampling.LANCZOS)
    aligned,regions=_ruled_cells(small)
    output=image
    if aligned is not small:
        matrix=np.asarray(aligned.info['ocr_layout_transform'])
        matrix[:,2]/=scale
        rgb=cv2.warpAffine(np.asarray(image.convert('RGB')),matrix,(width,height),borderValue=(255,255,255))
        output=Image.fromarray(rgb);output.info['ocr_layout_transform']=matrix.tolist()
        aligned.close()
    for region in regions:
        region['bbox']=tuple(v/scale for v in region['bbox'])
        region['xs']=[v/scale for v in region['xs']];region['ys']=[v/scale for v in region['ys']]
        for cell in region['cells']:cell['bbox']=tuple(v/scale for v in cell['bbox'])
    small.close()
    return output,regions
