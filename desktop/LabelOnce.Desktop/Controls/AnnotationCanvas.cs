using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using LabelOnce.Core;
namespace LabelOnce.Desktop.Controls;

public sealed record SamPromptState(string ObjectId,double[][] Points,int[] Labels,double[]? Box,double[]? Roi);

public sealed class AnnotationCanvas : FrameworkElement
{
    public Viewport View { get; } = new();
    public List<Annotation> Boxes { get; private set; }=[];
    public string[] Classes { get; set; }=[];
    public int ClassId { get; set; }
    public int Selected { get; private set; }=-1;
    public int NextTargetId { get; set; }
    public bool Video { get; private set; }
    public bool ReadOnly { get; set; }
    public string Mode { get; private set; }="select";
    public event Action? Changed;
    public event Action? EditStarted;
    public event Action? SelectionChanged;
    public event Action<int>? Navigate;
    public event Action? Confirm;
    public event Action<double[],bool>? SamPrompt;
    public event Action? ViewChanged;
    public event Action<double[]>? RoiPrompt;
    public event Action? NewTarget;

    public event Action<SamPromptState,bool>? SamStateChanged;
    public event Action<string>? ModeChanged;
    public event Action<Annotation>? CandidateReady;
    public bool HasCandidate => (pendingRectangle is { } r && r.X2-r.X1 >= 2.0/View.Width && r.Y2-r.Y1 >= 2.0/View.Height) || samCandidate is not null;
    public bool HasDraft => pendingRectangle is not null || samCandidate is not null || prompts.Count>0 || samBox is not null || newPolygon.Count>0;
    int vertexRing=-1,vertex=-1;
    readonly List<double[]> newPolygon=[];
    readonly List<(double[] Point,bool Positive)> prompts=[];
    double[]? roi;
    List<Annotation>? samBefore;
    string? samObject;
    double[]? samBox;
    sealed record EditState(List<Annotation> Boxes,SamPromptState Sam,List<Annotation>? Before,Annotation? Candidate);
    readonly List<EditState> history=[];
    int historyIndex=-1;
    SamPromptState PromptState()=>new(samObject??=Guid.NewGuid().ToString(),prompts.Select(p=>(double[])p.Point.Clone()).ToArray(),prompts.Select(p=>p.Positive?1:0).ToArray(),samBox is null?null:(double[])samBox.Clone(),roi is null?null:[roi[0]*View.Width,roi[1]*View.Height,roi[2]*View.Width,roi[3]*View.Height]);
    void ResetHistory(){history.Clear();historyIndex=-1;RecordHistory();}
    void RecordHistory()
    {
        if(historyIndex+1<history.Count)history.RemoveRange(historyIndex+1,history.Count-historyIndex-1);
        history.Add(new(Boxes.Select(b=>b.Copy()).ToList(),PromptState(),samBefore?.Select(b=>b.Copy()).ToList(),samCandidate?.Copy()));
        if(history.Count>100)history.RemoveAt(0);historyIndex=history.Count-1;
    }
    void Restore(EditState state)
    {
        samCandidate=state.Candidate?.Copy();pendingRectangle=null;drawing=false;Boxes=state.Boxes.Select(b=>b.Copy()).ToList();samObject=state.Sam.ObjectId;samBox=state.Sam.Box;
        prompts.Clear();for(int i=0;i<state.Sam.Points.Length;i++)prompts.Add(((double[])state.Sam.Points[i].Clone(),state.Sam.Labels[i]==1));
        roi=state.Sam.Roi is { } r?[r[0]/View.Width,r[1]/View.Height,r[2]/View.Width,r[3]/View.Height]:null;
        samBefore=state.Before?.Select(b=>b.Copy()).ToList();Selected=-1;vertex=vertexRing=-1;
        SamStateChanged?.Invoke(PromptState(),false);
    }
    BitmapSource? raster;
    string? loadedSource;
    PointD start, last;
    Annotation? before;
    Annotation? clipboard;
    Annotation? pendingRectangle;
    Annotation? samCandidate;
    bool panning, dragging, drawing, space;
    int handle=-1, navStep;
    readonly DispatcherTimer navigation=new();
    static readonly Brush Cyan=new SolidColorBrush(Color.FromRgb(66,217,234));
    static readonly Brush Orange=new SolidColorBrush(Color.FromRgb(255,177,86));
    public AnnotationCanvas()
    {
        Focusable=true; ClipToBounds=true;
        InputMethod.SetIsInputMethodEnabled(this,false);
        SizeChanged+=(s,e)=>{View.Resize(ActualWidth,ActualHeight);InvalidateVisual();ViewChanged?.Invoke();};
        LostKeyboardFocus+=(s,e)=>StopNavigation();
        IsVisibleChanged+=(s,e)=>{if(!IsVisible)StopNavigation();};
        navigation.Tick+=(s,e)=>{navigation.Interval=TimeSpan.FromMilliseconds(100);Navigate?.Invoke(navStep);};
    }
    public void StopNavigation() { navigation.Stop();navStep=0;space=false; }
    public void Load(string path,string source,int width,int height,int orientation,IEnumerable<Annotation> boxes,bool video)
    {
        using(var stream=System.IO.File.OpenRead(path))
        {
            var bitmap=new BitmapImage();bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.StreamSource=stream;bitmap.EndInit();bitmap.Freeze();raster=bitmap;
        }
        if(!video||loadedSource!=source)NextTargetId=0;
        loadedSource=source;Video=video;View.Resize(ActualWidth,ActualHeight);View.Load(source,width,height,orientation,video);
        Boxes=boxes.Select(b=>b.Copy()).ToList();Selected=-1;
        NextTargetId=Math.Max(NextTargetId,Boxes.Select(b=>b.TargetId+1).DefaultIfEmpty(0).Max());
        Cursor=Mode=="select"?Cursors.Arrow:Cursors.Cross;drawing=dragging=panning=false;vertex=vertexRing=-1;newPolygon.Clear();prompts.Clear();roi=samBox=null;samBefore=null;samObject=null;pendingRectangle=samCandidate=null;ResetHistory();InvalidateVisual();SelectionChanged?.Invoke();ViewChanged?.Invoke();ModeChanged?.Invoke(Mode);
    }
    public void Clear()
    {
        raster=null;loadedSource=null;Boxes=[];Selected=-1;NextTargetId=0;Video=false;prompts.Clear();roi=samBox=null;samBefore=null;samObject=null;pendingRectangle=samCandidate=null;ResetHistory();View.Load("",1,1,1,false);InvalidateVisual();SelectionChanged?.Invoke();ViewChanged?.Invoke();Mode="select";Cursor=Cursors.Arrow;ModeChanged?.Invoke(Mode);
    }
    public void SetBoxes(IEnumerable<Annotation> boxes,bool record=true)
    {
        if(record&&ReadOnly)return;
        Boxes=boxes.Select(b=>b.Copy()).ToList();Selected=-1;
        NextTargetId=Math.Max(NextTargetId,Boxes.Select(b=>b.TargetId+1).DefaultIfEmpty(0).Max());
        if(record)Commit();else {ResetHistory();InvalidateVisual();SelectionChanged?.Invoke();}
    }
    // 程序化聚焦画布时，不打断正在输入的文本框/下拉框，避免输入中途焦点被抢走。
    public void Refocus(){ if(Keyboard.FocusedElement is not System.Windows.Controls.Primitives.TextBoxBase) Focus(); }
    public void SetMode(string mode) { if(ReadOnly)return;Mode=mode;Cursor=mode=="select"?Cursors.Arrow:Cursors.Cross;Refocus();ModeChanged?.Invoke(mode);InvalidateVisual(); }
    public void Fit() { View.Fit();InvalidateVisual();ViewChanged?.Invoke(); }
    public void Select(int index) { Selected=index;InvalidateVisual();SelectionChanged?.Invoke();Refocus(); }
    public void Delete() { if(ReadOnly||Selected<0||Selected>=Boxes.Count)return;
        if(vertex>=0&&Boxes[Selected].Polygons is { } polys&&vertexRing>=0&&vertexRing<polys.Count){if(polys[vertexRing].Count<=3)return;polys[vertexRing].RemoveAt(vertex);UpdateBounds(Boxes[Selected]);vertex=-1;Commit();return;}Boxes.RemoveAt(Selected);Selected=-1;Commit(); }
    public void Undo(int step)
    {
        if(ReadOnly)return;
        if(historyIndex<0||history.Count==0)return;
        var current=PromptState();var saved=history[historyIndex].Sam;
        bool pending=System.Text.Json.JsonSerializer.Serialize(current)!=System.Text.Json.JsonSerializer.Serialize(saved);
        int next=pending&&step<0?historyIndex:historyIndex+step;if(next<0||next>=history.Count)return;
        var previous=System.Text.Json.JsonSerializer.Serialize(Boxes);historyIndex=next;Restore(history[next]);InvalidateVisual();if(previous!=System.Text.Json.JsonSerializer.Serialize(Boxes))Changed?.Invoke();SelectionChanged?.Invoke();
    }
    public void Copy() { if(Selected>=0&&Selected<Boxes.Count)clipboard=Boxes[Selected].Copy(); }
    public void Paste()
    {
        if(ReadOnly||clipboard is null)return;
        var b=clipboard.Copy();double dx=Math.Min(20/View.Width,1-b.X2),dy=Math.Min(20/View.Height,1-b.Y2);
        b.SetBounds(b.X1+dx,b.Y1+dy,b.X2+dx,b.Y2+dy);b.TargetId=Video?NextTargetId++:-1;b.ObjectId=Guid.NewGuid().ToString();
        Boxes.Add(b);Selected=Boxes.Count-1;Commit();
    }
    public void NewSam(){if(ReadOnly)return;samBefore=null;samObject=null;samBox=null;samCandidate=null;Selected=-1;prompts.Clear();roi=null;NewTarget?.Invoke();SamStateChanged?.Invoke(PromptState(),false);SetMode("sam-point");InvalidateVisual();}
    public void ClearSam(){if(ReadOnly)return;var baseline=samBefore;NewSam();if(baseline is not null){Boxes=baseline.Select(b=>b.Copy()).ToList();Selected=-1;Commit();}}
    public void UpdateSam(IEnumerable<Annotation> boxes)
    {
        samCandidate=boxes.FirstOrDefault()?.Copy();
        if(samCandidate is not null){samObject=samCandidate.ObjectId;var prior=Boxes.FirstOrDefault(x=>x.ObjectId==samObject);if(prior is not null)samCandidate.TargetId=prior.TargetId;}
        if(historyIndex>=0)history[historyIndex]=history[historyIndex] with {Candidate=samCandidate?.Copy()};
        InvalidateVisual();
    }
    public void CommitCandidate(int classId)
    {
        if(!HasCandidate||ReadOnly)return;
        var candidate=pendingRectangle??samCandidate;
        if(candidate is null)return;
        var box=candidate.Copy();box.ClassId=classId;
        int existing=Boxes.FindIndex(x=>x.ObjectId==box.ObjectId);
        if(existing>=0){box.TargetId=Boxes[existing].TargetId;Boxes[existing]=box;Selected=existing;}
        else{box.TargetId=Video?NextTargetId++:-1;Boxes.Add(box);Selected=Boxes.Count-1;}
        pendingRectangle=samCandidate=null;drawing=false;prompts.Clear();samBox=null;roi=null;samObject=null;Selected=-1;SamStateChanged?.Invoke(PromptState(),false);Commit();SetMode("select");
    }
    public void DiscardCandidate(){samObject=null;samBefore=null;newPolygon.Clear();pendingRectangle=samCandidate=null;drawing=false;prompts.Clear();samBox=null;roi=null;NewTarget?.Invoke();InvalidateVisual();}
    void FinishPolygon()
    {
        var points=newPolygon.DistinctBy(v=>(v[0],v[1])).Select(v=>(double[])v.Clone()).ToList();
        if(points.Count<3)return;
        double area=0;for(int i=0;i<points.Count;i++){var a=points[i];var b=points[(i+1)%points.Count];area+=a[0]*b[1]-b[0]*a[1];}
        if(Math.Abs(area)*View.Width*View.Height<2)return;
        pendingRectangle=new Annotation{ObjectId=Guid.NewGuid().ToString(),Polygons=[points]};UpdateBounds(pendingRectangle);newPolygon.Clear();InvalidateVisual();Dispatcher.BeginInvoke(RequestCandidateCategory);
    }
    public void RequestCandidateCategory(){if(!HasCandidate)return;if(pendingRectangle is { } rectangle)CandidateReady?.Invoke(rectangle);else if(samCandidate is { } sam)CandidateReady?.Invoke(sam);}
    static void UpdateBounds(Annotation b)
    {
        var points=b.Polygons!.SelectMany(p=>p).ToList();b.X1=points.Min(p=>p[0]);b.Y1=points.Min(p=>p[1]);b.X2=points.Max(p=>p[0]);b.Y2=points.Max(p=>p[1]);b.Origin="人工";b.RawPolygons=null;
    }
    bool HitVertex(Point p)
    {
        vertex=vertexRing=-1;if(Selected<0||Selected>=Boxes.Count||Boxes[Selected].Polygons is not { } rings)return false;
        for(int r=0;r<rings.Count;r++)for(int i=0;i<rings[r].Count;i++)if((Point(Screen(rings[r][i][0],rings[r][i][1]))-p).Length<=9){vertexRing=r;vertex=i;return true;}
        return false;
    }
    bool InsertVertex(Point p)
    {
        if(Selected<0||Selected>=Boxes.Count||Boxes[Selected].Polygons is not { } rings)return false;
        for(int r=0;r<rings.Count;r++)for(int i=0;i<rings[r].Count;i++){
            var a=Point(Screen(rings[r][i][0],rings[r][i][1]));var next=rings[r][(i+1)%rings[r].Count];var b=Point(Screen(next[0],next[1]));var ab=b-a;double t=Math.Clamp(Vector.Multiply(p-a,ab)/Math.Max(ab.LengthSquared,1e-9),0,1);
            if((p-(a+ab*t)).Length<=9){var projected=a+ab*t;var raw=View.ToNormalized(new(projected.X,projected.Y));rings[r].Insert(i+1,[raw.X,raw.Y]);vertexRing=r;vertex=i+1;UpdateBounds(Boxes[Selected]);Commit();return true;}}
        return false;
    }
    public void Add(IEnumerable<Annotation> boxes) { if(ReadOnly)return;Boxes.AddRange(boxes.Select(b=>b.Copy()));Commit(); }
    public void Commit() { RecordHistory();InvalidateVisual();Changed?.Invoke();SelectionChanged?.Invoke(); }
    PointD Screen(double x,double y)=>View.ToScreen(new(x*View.Width,y*View.Height));
    static Point Point(PointD p)=>new(p.X,p.Y);
    Rect Bounds(Annotation b)
    {
        var points=new[]{Screen(b.X1,b.Y1),Screen(b.X2,b.Y1),Screen(b.X1,b.Y2),Screen(b.X2,b.Y2)};
        return new Rect(new Point(points.Min(p=>p.X),points.Min(p=>p.Y)),new Point(points.Max(p=>p.X),points.Max(p=>p.Y)));
    }
    static Point[] Handles(Rect r)=>[r.TopLeft,new(r.Left+r.Width/2,r.Top),r.TopRight,new(r.Right,r.Top+r.Height/2),r.BottomRight,new(r.Left+r.Width/2,r.Bottom),r.BottomLeft,new(r.Left,r.Top+r.Height/2)];
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);dc.DrawRectangle(new SolidColorBrush(Color.FromRgb(16,20,26)),null,new Rect(0,0,ActualWidth,ActualHeight));
        if(raster is null)
        {
            Text(dc,"打开项目并导入图片，或选择视频",new(32,32),Cyan,16);return;
        }
        var a=View.ToScreen(new(0,0));var x=View.ToScreen(new(1,0));var y=View.ToScreen(new(0,1));
        dc.PushTransform(new MatrixTransform(new Matrix(x.X-a.X,x.Y-a.Y,y.X-a.X,y.Y-a.Y,a.X,a.Y)));
        dc.DrawImage(raster,new Rect(0,0,View.Width,View.Height));dc.Pop();
        for(int i=0;i<Boxes.Count;i++)
        {
            var box=Boxes[i];bool selected=i==Selected;Brush ink=box.Origin=="AI"?Orange:Cyan;
            var pen=new Pen(ink,selected?2:1.5);if(box.Origin=="AI")pen.DashStyle=DashStyles.Dash;
            if(box.Polygons is not null)
            {
                var geo=new StreamGeometry{FillRule=FillRule.EvenOdd};using(var g=geo.Open())
                foreach(var poly in box.Polygons.Concat(box.Holes??[]).Where(p=>p.Count>=3))
                {
                    g.BeginFigure(Point(Screen(poly[0][0],poly[0][1])),true,true);g.PolyLineTo(poly.Skip(1).Select(p=>Point(Screen(p[0],p[1]))).ToArray(),true,false);
                }
                geo.Freeze();dc.DrawGeometry(new SolidColorBrush(Color.FromArgb(48,255,177,86)),new Pen(ink,1.5),geo);
            }
            var rect=Bounds(box);
            if(box.Polygons is null||selected)dc.DrawRectangle(null,pen,rect);
            string name=box.ClassId>=0&&box.ClassId<Classes.Length?Classes[box.ClassId]:$"class_{box.ClassId}";
            string label=(box.TargetId>=0?$"{box.TargetId} · ":"")+name+(box.Score is not null?$" {box.Score:P0}":"");
            dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromArgb(225,20,28,36)),null,new Rect(rect.Left,Math.Max(0,rect.Top-23),Math.Max(60,label.Length*8+12),22),4,4);
            Text(dc,label,new(rect.Left+5,Math.Max(1,rect.Top-22)),ink,12);
            if(selected&&box.Polygons is { } rings)foreach(var ring in rings)foreach(var v in ring){var p=Point(Screen(v[0],v[1]));dc.DrawEllipse(Cyan,new Pen(Brushes.Black,1),p,4,4);}
            if(selected&&box.Polygons is null)foreach(var h in Handles(rect))dc.DrawRectangle(Cyan,new Pen(Brushes.Black,1),new Rect(h.X-4,h.Y-4,8,8));
        }
        Text(dc,$"{Mode switch{"sam-point"=>"＋ 正点 Q","sam-negative"=>"− 负点 E","roi"=>"当前对象 ROI","polygon"=>"多边形 · Esc 闭合并确认类别","select"=>"选择 / 编辑","draw"=>drawing?"再次单击确认矩形":"单击设置矩形起点","sam-box"=>"SAM 框提示",_=>Mode}}",new(12,12),Cyan,12);
        foreach(var prompt in prompts){var p=View.ToScreen(new(prompt.Point[0],prompt.Point[1]));dc.DrawEllipse(prompt.Positive?Brushes.LimeGreen:Brushes.OrangeRed,new Pen(Brushes.Black,1),Point(p),4,4);Text(dc,prompt.Positive?"+":"−",new(p.X+5,p.Y-10),Brushes.White,14);}
        if(roi is { } rr){var a1=Screen(rr[0],rr[1]);var a2=Screen(rr[2],rr[3]);dc.DrawRectangle(null,new Pen(Brushes.LimeGreen,2){DashStyle=DashStyles.Dash},new Rect(Point(a1),Point(a2)));}
        for(int i=0;i<newPolygon.Count;i++){var q=Point(Screen(newPolygon[i][0],newPolygon[i][1]));dc.DrawEllipse(Cyan,null,q,4,4);if(i>0)dc.DrawLine(new Pen(Cyan,2),Point(Screen(newPolygon[i-1][0],newPolygon[i-1][1])),q);}
        if(Mode=="polygon"&&newPolygon.Count>0)dc.DrawLine(new Pen(Cyan,1.5){DashStyle=DashStyles.Dash},Point(Screen(newPolygon[^1][0],newPolygon[^1][1])),Point(Screen(last.X,last.Y)));
        if(pendingRectangle is { } draft && !drawing){if(draft.Polygons is { } rings){foreach(var ring in rings){var geometry=new StreamGeometry();using(var g=geometry.Open()){g.BeginFigure(Point(Screen(ring[0][0],ring[0][1])),false,true);g.PolyLineTo(ring.Skip(1).Select(v=>Point(Screen(v[0],v[1]))).ToArray(),true,false);}dc.DrawGeometry(null,new Pen(Cyan,2),geometry);}}else dc.DrawRectangle(null,new Pen(Cyan,2){DashStyle=DashStyles.Dash},Bounds(draft));}
        if(samCandidate is { } candidate && candidate.Polygons is { } candidateRings){foreach(var ring in candidateRings.Concat(candidate.Holes??[]).Where(r=>r.Count>=3)){var geo=new StreamGeometry();using(var g=geo.Open()){g.BeginFigure(Point(Screen(ring[0][0],ring[0][1])),false,true);g.PolyLineTo(ring.Skip(1).Select(v=>Point(Screen(v[0],v[1]))).ToArray(),true,false);}geo.Freeze();dc.DrawGeometry(null,new Pen(Brushes.LimeGreen,2){DashStyle=DashStyles.Dash},geo);}}
        if(drawing){var p=View.ToScreen(new(start.X*View.Width,start.Y*View.Height));var q=View.ToScreen(new(last.X*View.Width,last.Y*View.Height));dc.DrawRectangle(null,new Pen(Cyan,1.5),new Rect(Point(p),Point(q)));}
    }
    void Text(DrawingContext dc,string text,Point at,Brush brush,double size) => dc.DrawText(new FormattedText(text,CultureInfo.CurrentUICulture,FlowDirection.LeftToRight,new Typeface("Segoe UI"),size,brush,VisualTreeHelper.GetDpi(this).PixelsPerDip),at);
    protected override void OnMouseWheel(MouseWheelEventArgs e)
    {
        if(raster is null)return;
        if(Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            var p=e.GetPosition(this);View.Zoom(new(p.X,p.Y),e.Delta>0?1.2:1/1.2);
        }
        else View.ScrollVertical(e.Delta*0.6);
        InvalidateVisual();ViewChanged?.Invoke();e.Handled=true;
    }
    protected override void OnMouseDown(MouseButtonEventArgs e)
    {
        Focus();if(raster is null)return;var p=e.GetPosition(this);last=new(p.X,p.Y);
        if(e.ChangedButton==MouseButton.Middle||(space&&e.ChangedButton==MouseButton.Left)){panning=true;CaptureMouse();e.Handled=true;return;}
        if(e.ChangedButton==MouseButton.Right&&!ReadOnly&&!HasDraft)
        {
            Selected=Boxes.FindLastIndex(b=>Bounds(b).Contains(p));vertex=vertexRing=-1;
            InvalidateVisual();SelectionChanged?.Invoke();
            if(Selected>=0){var id=Boxes[Selected].ObjectId;var menu=new System.Windows.Controls.ContextMenu();var item=new System.Windows.Controls.MenuItem{Header="删除对象",InputGestureText="Del"};item.Click+=(_,_)=>{Selected=Boxes.FindIndex(b=>b.ObjectId==id);vertex=vertexRing=-1;EditStarted?.Invoke();Delete();};menu.Items.Add(item);menu.PlacementTarget=this;ContextMenu=menu;menu.IsOpen=true;}
            e.Handled=true;return;
        }
        if(e.ChangedButton!=MouseButton.Left||ReadOnly)return;
        start=View.ToNormalized(last);
        if(Mode is "sam-point" or "sam-negative"){
            if(prompts.Count==0&&samCandidate is null&&Selected>=0&&Selected<Boxes.Count){var selected=Boxes[Selected];samObject=selected.ObjectId;samBox=[selected.X1*View.Width,selected.Y1*View.Height,selected.X2*View.Width,selected.Y2*View.Height];}
            var q=new[]{start.X*View.Width,start.Y*View.Height};prompts.Add((q,Mode=="sam-point"));RecordHistory();SamStateChanged?.Invoke(PromptState(),true);SamPrompt?.Invoke(q,Mode=="sam-point");InvalidateVisual();e.Handled=true;return;}
        if(Mode=="polygon"){
            if(pendingRectangle is not null){RequestCandidateCategory();return;}
            if(e.ClickCount==2&&newPolygon.Count>=3)FinishPolygon();
            else {newPolygon.Add([start.X,start.Y]);last=start;}InvalidateVisual();return;}
        if(e.ClickCount==2&&InsertVertex(p)){e.Handled=true;return;}
        if(Mode is "draw") { if(pendingRectangle is not null&&!drawing){RequestCandidateCategory();return;} if(pendingRectangle is null){ pendingRectangle=new Annotation{X1=start.X,Y1=start.Y,X2=start.X,Y2=start.Y}; drawing=true; last=start; } else { var anchor=pendingRectangle; var end=start;drawing=false;pendingRectangle=new Annotation{X1=Math.Clamp(Math.Min(anchor.X1,end.X),0,1),Y1=Math.Clamp(Math.Min(anchor.Y1,end.Y),0,1),X2=Math.Clamp(Math.Max(anchor.X1,end.X),0,1),Y2=Math.Clamp(Math.Max(anchor.Y1,end.Y),0,1)};if(pendingRectangle.X2-pendingRectangle.X1>=2.0/View.Width&&pendingRectangle.Y2-pendingRectangle.Y1>=2.0/View.Height)Dispatcher.BeginInvoke(RequestCandidateCategory);else pendingRectangle=null; } InvalidateVisual(); e.Handled=true; return; }
        if(Mode is "sam-box" or "roi") {drawing=true;last=start;CaptureMouse();e.Handled=true;return;}
        handle=-1;
        bool hitVertex=HitVertex(p);
        if(!hitVertex&&Selected>=0&&Selected<Boxes.Count)
        {
            var hs=Boxes[Selected].Polygons is null?Handles(Bounds(Boxes[Selected])):[];handle=Array.FindIndex(hs,h=>(h-p).Length<=10);
        }
        if(!hitVertex&&handle<0)Selected=Boxes.FindLastIndex(b=>Bounds(b).Contains(p));
        if(Selected>=0){EditStarted?.Invoke();before=Boxes[Selected].Copy();dragging=true;CaptureMouse();}
        InvalidateVisual();SelectionChanged?.Invoke();e.Handled=true;
    }
    protected override void OnMouseMove(MouseEventArgs e)
    {
        var p=e.GetPosition(this);var screen=new PointD(p.X,p.Y);
        if(panning){View.Pan(screen-last);last=screen;InvalidateVisual();ViewChanged?.Invoke();return;}
        if(ReadOnly)return;
        if(Mode=="polygon"&&newPolygon.Count>0){last=View.ToNormalized(screen);InvalidateVisual();return;}
        if(drawing){last=View.ToNormalized(screen);InvalidateVisual();return;}
        if(dragging&&before is not null&&Selected>=0)
        {
            var now=View.ToNormalized(screen);var b=before.Copy();
            if(vertex>=0&&vertexRing>=0&&b.Polygons is { } rings){double nx=now.X,ny=now.Y;if(b.Roi is { } r){nx=Math.Clamp(nx,r[0],r[2]);ny=Math.Clamp(ny,r[1],r[3]);}rings[vertexRing][vertex]=[nx,ny];UpdateBounds(b);}
            else if(handle<0)
            {
                double dx=Math.Clamp(now.X-start.X,(b.Roi?[0]??0)-b.X1,(b.Roi?[2]??1)-b.X2),dy=Math.Clamp(now.Y-start.Y,(b.Roi?[1]??0)-b.Y1,(b.Roi?[3]??1)-b.Y2);
                b.SetBounds(b.X1+dx,b.Y1+dy,b.X2+dx,b.Y2+dy);
            }
            else
            {
                // Handle movement is computed in display space then inverse-mapped to raw pixels.
                var r=Bounds(before);double left=r.Left,top=r.Top,right=r.Right,bottom=r.Bottom;
                if(handle is 0 or 6 or 7)left=p.X;if(handle is 2 or 3 or 4)right=p.X;
                if(handle is 0 or 1 or 2)top=p.Y;if(handle is 4 or 5 or 6)bottom=p.Y;
                var a=View.ToNormalized(new(left,top));var z=View.ToNormalized(new(right,bottom));
                b.SetBounds(a.X,a.Y,z.X,z.Y);
            }
            Boxes[Selected]=b;InvalidateVisual();
        }
    }
    protected override void OnMouseUp(MouseButtonEventArgs e)
    {
        if(panning){panning=false;ReleaseMouseCapture();return;}
        if(Mode=="draw")return;
        if(drawing)
        {
            drawing=false;ReleaseMouseCapture();
            double x1=Math.Min(start.X,last.X),y1=Math.Min(start.Y,last.Y),x2=Math.Max(start.X,last.X),y2=Math.Max(start.Y,last.Y);
            if((x2-x1)*View.Width>=2&&(y2-y1)*View.Height>=2)
            {
                if(Mode=="roi"){roi=[x1,y1,x2,y2];RecordHistory();SamStateChanged?.Invoke(PromptState(),true);RoiPrompt?.Invoke([x1*View.Width,y1*View.Height,x2*View.Width,y2*View.Height]);}
                else if(Mode=="sam-box"){samBox=[x1*View.Width,y1*View.Height,x2*View.Width,y2*View.Height];RecordHistory();SamStateChanged?.Invoke(PromptState(),true);SamPrompt?.Invoke(samBox,false);}
                
            }
            InvalidateVisual();
        }
        if(dragging){dragging=false;ReleaseMouseCapture();Commit();}
    }
    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);bool ctrl=Keyboard.Modifiers.HasFlag(ModifierKeys.Control);
        if(e.Key==Key.Space){space=true;e.Handled=true;return;}
        if(e.Key==Key.R){Fit();e.Handled=true;return;}
        if(ReadOnly)return;
        switch(e.Key)
        {
            case Key.A:case Key.D:
                if(!e.IsRepeat){navStep=e.Key==Key.A?-1:1;Navigate?.Invoke(navStep);navigation.Interval=TimeSpan.FromMilliseconds(300);navigation.Start();}break;
            case Key.F:if(!e.IsRepeat)Confirm?.Invoke();break;
            case Key.W:SetMode("draw");break;
            case Key.Q:SetMode("sam-point");break;
            case Key.E:SetMode("sam-negative");break;
            case Key.P:SetMode("polygon");break;
            case Key.Escape:if(Mode=="polygon"&&newPolygon.Count>=3){FinishPolygon();break;}if(dragging&&before is not null&&Selected>=0&&Selected<Boxes.Count)Boxes[Selected]=before.Copy();dragging=drawing=false;DiscardCandidate();newPolygon.Clear();ReleaseMouseCapture();SetMode("select");break;

            case Key.Delete:Delete();break;
            case Key.Z when ctrl:Undo(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)?1:-1);break;
            case Key.Y when ctrl:Undo(1);break;
            case Key.C when ctrl:Copy();break;
            case Key.V when ctrl:Paste();break;
            case Key.Left:case Key.Right:case Key.Up:case Key.Down:
                if(Selected>=0){var b=Boxes[Selected];double dx=e.Key==Key.Left?-1/View.Width:e.Key==Key.Right?1/View.Width:0,dy=e.Key==Key.Up?-1/View.Height:e.Key==Key.Down?1/View.Height:0;dx=Math.Clamp(dx,-b.X1,1-b.X2);dy=Math.Clamp(dy,-b.Y1,1-b.Y2);b.SetBounds(b.X1+dx,b.Y1+dy,b.X2+dx,b.Y2+dy);Commit();}break;
            default:return;
        }
        e.Handled=true;InvalidateVisual();
    }
    protected override void OnKeyUp(KeyEventArgs e){if(e.Key is Key.A or Key.D)StopNavigation();if(e.Key==Key.Space)space=false;base.OnKeyUp(e);}
}
