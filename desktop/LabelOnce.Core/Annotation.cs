using System.Text.Json.Serialization;
namespace LabelOnce.Core;

public sealed record Annotation
{
    [JsonPropertyName("cls")] public int ClassId { get; set; }
    [JsonPropertyName("x1")] public double X1 { get; set; }
    [JsonPropertyName("y1")] public double Y1 { get; set; }
    [JsonPropertyName("x2")] public double X2 { get; set; }
    [JsonPropertyName("y2")] public double Y2 { get; set; }
    [JsonPropertyName("origin")] public string Origin { get; set; } = "人工";
    [JsonPropertyName("score")] public double? Score { get; set; }
    [JsonPropertyName("polygons")] public List<List<double[]>>? Polygons { get; set; }
    [JsonPropertyName("object_id")] public string? ObjectId { get; set; } = Guid.NewGuid().ToString();
    [JsonPropertyName("roi")] public double[]? Roi { get; set; }
    [JsonPropertyName("raw_polygons")] public List<List<double[]>>? RawPolygons { get; set; }
    [JsonPropertyName("holes")] public List<List<double[]>>? Holes { get; set; }
    [JsonPropertyName("target_id")] public int TargetId { get; set; } = -1;
    public Annotation Copy() => this with { Polygons=CopyRings(Polygons), RawPolygons=CopyRings(RawPolygons), Holes=CopyRings(Holes), Roi=Roi is null?null:(double[])Roi.Clone() };
    static List<List<double[]>>? CopyRings(List<List<double[]>>? rings)=>rings?.Select(poly=>poly.Select(p=>(double[])p.Clone()).ToList()).ToList();
    public void SetBounds(double x1,double y1,double x2,double y2)
    {
        (x1,x2)=(Math.Clamp(Math.Min(x1,x2),0,1),Math.Clamp(Math.Max(x1,x2),0,1));
        (y1,y2)=(Math.Clamp(Math.Min(y1,y2),0,1),Math.Clamp(Math.Max(y1,y2),0,1));
        if (Roi is { } roi)
        {
            x1=Math.Clamp(x1,roi[0],roi[2]);x2=Math.Clamp(x2,roi[0],roi[2]);
            y1=Math.Clamp(y1,roi[1],roi[3]);y2=Math.Clamp(y2,roi[1],roi[3]);
        }
        foreach(var rings in new[]{Polygons,Holes})
        if (rings is not null)
            foreach(var p in rings.SelectMany(p=>p))
            {
                p[0]=Math.Clamp(x1+(p[0]-X1)/Math.Max(X2-X1,1e-9)*(x2-x1),0,1);
                p[1]=Math.Clamp(y1+(p[1]-Y1)/Math.Max(Y2-Y1,1e-9)*(y2-y1),0,1);
            }
        X1=x1;Y1=y1;X2=x2;Y2=y2;Origin="人工";RawPolygons=null;
    }
}

public sealed class AnnotationHistory
{
    readonly List<List<Annotation>> states=[];
    int index=-1;
    public void Reset(IEnumerable<Annotation> boxes) { states.Clear();index=-1;Record(boxes); }
    public void Record(IEnumerable<Annotation> boxes)
    {
        if(index+1<states.Count)states.RemoveRange(index+1,states.Count-index-1);
        states.Add(boxes.Select(b=>b.Copy()).ToList());
        if(states.Count>100)states.RemoveAt(0);
        index=states.Count-1;
    }
    public List<Annotation>? Step(int direction)
    {
        int next=index+direction;
        if(next<0||next>=states.Count)return null;
        index=next;return states[index].Select(b=>b.Copy()).ToList();
    }
}

