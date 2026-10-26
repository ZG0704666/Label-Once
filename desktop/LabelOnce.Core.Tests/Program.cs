using LabelOnce.Core;
int assertions=0;
void Check(bool condition,string message){assertions++;if(!condition)throw new Exception(message);}
void Near(double a,double b,string message)=>Check(Math.Abs(a-b)<1e-7,message+$" ({a} != {b})");
foreach(var size in new[]{(1920,1080),(1080,1920),(1000,1000),(8000,500)})
foreach(int orientation in Enumerable.Range(1,8))
foreach(double dpi in new[]{1d,1.25,1.5,2})
foreach(var viewport in new[]{(1366,768),(1920,1080),(2560,1440)})
{
    var v=new Viewport();v.Resize(viewport.Item1/dpi-344,viewport.Item2/dpi-160);v.Load("image",size.Item1,size.Item2,orientation,false);
    Check(v.DisplayWidth*v.Scale<=v.AvailableWidth-16+1e-7,"width fit");Check(v.DisplayHeight*v.Scale<=v.AvailableHeight-16+1e-7,"height fit");
    Near(v.Offset.X*2+v.DisplayWidth*v.Scale,v.AvailableWidth,"center X");Near(v.Offset.Y*2+v.DisplayHeight*v.Scale,v.AvailableHeight,"center Y");
    foreach(var p in new[]{new PointD(0,0),new PointD(size.Item1,size.Item2),new PointD(123,45)})
    {var q=v.ToRaw(v.ToScreen(p));Near(q.X,p.X,"EXIF inverse X");Near(q.Y,p.Y,"EXIF inverse Y");}
    var anchor=new PointD(140,120);var raw=v.ToRaw(anchor);v.Zoom(anchor,1.2);var after=v.ToScreen(raw);Near(after.X,anchor.X,"zoom anchor X");Near(after.Y,anchor.Y,"zoom anchor Y");
    var scale=v.Scale;var offset=v.Offset;v.Resize(1000,700);Near(v.Scale,scale,"manual resize scale");Check(v.Offset==offset,"manual resize offset");
    v.Load("image",size.Item1,size.Item2,orientation,true);Near(v.Scale,scale,"same video zoom preserved");
    v.Load("image",size.Item1,size.Item2,orientation,false);Check(v.IsFit,"image switch resets fit");
    v.Zoom(anchor,2);v.Load("new-video",size.Item1,size.Item2,orientation,true);Check(v.IsFit,"new video resets fit");
    v.Zoom(anchor,2);v.Load("new-video",size.Item1+1,size.Item2,orientation,true);Check(v.IsFit,"size change resets fit");
}
var annotation=new Annotation{X1=.1,Y1=.2,X2=.4,Y2=.6,Polygons=[[new[]{.1,.2},new[]{.4,.2},new[]{.4,.6}]],TargetId=7};
var history=new AnnotationHistory();history.Reset([annotation]);annotation.SetBounds(.2,.3,.8,.9);history.Record([annotation]);
var undone=history.Step(-1)!;Near(undone[0].Polygons![0][0][0],.1,"polygon undo");Check(undone[0].TargetId==7,"target ID undo");
var redone=history.Step(1)!;Near(redone[0].Polygons![0][1][0],.8,"polygon resize");
history.Step(-1);history.Record([]);Check(history.Step(1) is null,"new edit clears redo");
Console.WriteLine($"PASS: {assertions} geometry/history assertions");
