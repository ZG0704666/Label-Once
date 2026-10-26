namespace LabelOnce.Core;

public readonly record struct PointD(double X, double Y)
{
    public static PointD operator +(PointD a, PointD b) => new(a.X+b.X,a.Y+b.Y);
    public static PointD operator -(PointD a, PointD b) => new(a.X-b.X,a.Y-b.Y);
    public static PointD operator *(PointD a, double s) => new(a.X*s,a.Y*s);
}

/// <summary>Raw pixels → EXIF display pixels → viewport DIP. Labels always stay raw.</summary>
public sealed class Viewport
{
    public double Width { get; private set; }
    public double Height { get; private set; }
    public int Orientation { get; private set; } = 1;
    public double DisplayWidth => Orientation >= 5 ? Height : Width;
    public double DisplayHeight => Orientation >= 5 ? Width : Height;
    public double Scale { get; private set; } = 1;
    public PointD Offset { get; private set; }
    public bool IsFit { get; private set; } = true;
    public string Source { get; private set; } = "";
    public double AvailableWidth { get; private set; }
    public double AvailableHeight { get; private set; }

    public void Load(string source, double width, double height, int orientation, bool video)
    {
        if (width <= 0 || height <= 0) throw new ArgumentOutOfRangeException(nameof(width));
        orientation = orientation is >= 1 and <= 8 ? orientation : 1;
        bool reset = !video || Source != source || Width != width || Height != height || Orientation != orientation;
        Source=source; Width=width; Height=height; Orientation=orientation;
        if (reset) Fit();
    }
    public void Resize(double width, double height)
    {
        AvailableWidth=width; AvailableHeight=height;
        if (IsFit) Fit();
    }
    public void Fit()
    {
        IsFit=true;
        if (Width <= 0 || AvailableWidth <= 16 || AvailableHeight <= 16) return;
        Scale=Math.Min((AvailableWidth-16)/DisplayWidth,(AvailableHeight-16)/DisplayHeight);
        Offset=new((AvailableWidth-DisplayWidth*Scale)/2,(AvailableHeight-DisplayHeight*Scale)/2);
    }
    public PointD Orient(PointD p) => Orientation switch
    {
        2 => new(Width-p.X,p.Y), 3 => new(Width-p.X,Height-p.Y), 4 => new(p.X,Height-p.Y),
        5 => new(p.Y,p.X), 6 => new(Height-p.Y,p.X), 7 => new(Height-p.Y,Width-p.X),
        8 => new(p.Y,Width-p.X), _ => p
    };
    public PointD Unorient(PointD p) => Orientation switch
    {
        2 => new(Width-p.X,p.Y), 3 => new(Width-p.X,Height-p.Y), 4 => new(p.X,Height-p.Y),
        5 => new(p.Y,p.X), 6 => new(p.Y,Height-p.X), 7 => new(Width-p.Y,Height-p.X),
        8 => new(Width-p.Y,p.X), _ => p
    };
    public PointD ToScreen(PointD raw) => Orient(raw)*Scale+Offset;
    public PointD ToRaw(PointD screen) => Unorient((screen-Offset)*(1/Scale));
    public PointD ToNormalized(PointD screen)
    {
        var raw=ToRaw(screen);
        return new(Math.Clamp(raw.X/Width,0,1),Math.Clamp(raw.Y/Height,0,1));
    }
    public void Zoom(PointD anchor, double factor)
    {
        var raw=ToRaw(anchor);
        Scale=Math.Clamp(Scale*factor,.001,50);
        Offset=anchor-Orient(raw)*Scale; IsFit=false;
    }
    public void ScrollVertical(double delta)
    {
        var height=DisplayHeight*Scale;
        if(height<=AvailableHeight)return;
        Offset=new(Offset.X,Math.Clamp(Offset.Y+delta,AvailableHeight-height,0));
        IsFit=false;
    }
    public void Pan(PointD delta) { Offset+=delta; IsFit=false; }
}
