using LabelOnce.Core;

namespace LabelOnce.Desktop.ViewModels;

// Data-transfer records shared across the Studio view model. Kept separate from
// StudioViewModel so the view-model file holds behavior, not payload shapes.

public sealed record ImageEntry(string Name, string Path, string Status, string? Batch, string Source = "")
{
    public string Description => $"{Name} · {Status switch{"pending"=>"待完成","confirmed"=>"已完成","rejected"=>"已驳回",_=>"待标注"}}{Source}";
}

public sealed record ObjectEntry(int Index, int TargetId, string Name, string Origin);

public sealed record Document(string Path, string Source, int Width, int Height, int Orientation, List<Annotation> Boxes, bool Video);
