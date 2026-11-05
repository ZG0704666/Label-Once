using LabelOnce.Core;
using Xunit;

namespace LabelOnce.Core.Tests;

/// <summary>
/// Port of the former console harness's Viewport matrix. The full size x orientation x dpi x
/// viewport cross-product is kept as one exhaustive sweep so coverage matches the original; the
/// state-transition rules get their own named [Theory] cases for precise failure reporting.
/// </summary>
public class ViewportTests
{
    public static IEnumerable<object[]> Matrix()
    {
        foreach (var size in new[] { (1920.0, 1080.0), (1080.0, 1920.0), (1000.0, 1000.0), (8000.0, 500.0) })
        foreach (int orientation in Enumerable.Range(1, 8))
        foreach (double dpi in new[] { 1.0, 1.25, 1.5, 2.0 })
        foreach (var viewport in new[] { (1366.0, 768.0), (1920.0, 1080.0), (2560.0, 1440.0) })
            yield return new object[] { size.Item1, size.Item2, orientation, dpi, viewport.Item1, viewport.Item2 };
    }

    [Theory]
    [MemberData(nameof(Matrix))]
    public void Fit_zoom_roundtrip_and_centering(double imageW, double imageH, int orientation,
        double dpi, double viewW, double viewH)
    {
        var v = NewViewport(imageW, imageH, orientation, dpi, viewW, viewH, video: false);

        // The rendered image never exceeds the fit area (available minus 16 DIP padding).
        Assert.InRange(v.DisplayWidth * v.Scale, 0, v.AvailableWidth - 16 + 1e-7);
        Assert.InRange(v.DisplayHeight * v.Scale, 0, v.AvailableHeight - 16 + 1e-7);

        // Equal margins on both axes => centered.
        Assert.Equal((v.AvailableWidth - v.DisplayWidth * v.Scale) / 2, v.Offset.X, 7);
        Assert.Equal((v.AvailableHeight - v.DisplayHeight * v.Scale) / 2, v.Offset.Y, 7);

        // ToRaw inverts ToScreen across every EXIF orientation.
        foreach (var p in new[] { new PointD(0, 0), new PointD(imageW, imageH), new PointD(123, 45) })
        {
            var round = v.ToRaw(v.ToScreen(p));
            Assert.Equal(p.X, round.X, 7);
            Assert.Equal(p.Y, round.Y, 7);
        }

        // Zoom keeps its anchor point fixed on screen.
        var anchor = new PointD(140, 120);
        var raw = v.ToRaw(anchor);
        v.Zoom(anchor, 1.2);
        var after = v.ToScreen(raw);
        Assert.Equal(anchor.X, after.X, 7);
        Assert.Equal(anchor.Y, after.Y, 7);
    }

    [Theory]
    [MemberData(nameof(Matrix))]
    public void Manual_resize_preserves_scale_and_offset(double imageW, double imageH, int orientation,
        double dpi, double viewW, double viewH)
    {
        var v = NewViewport(imageW, imageH, orientation, dpi, viewW, viewH, video: false);
        v.Zoom(new PointD(viewW / 2, viewH / 2), 1.2); // leave fit mode so Resize won't re-fit
        double scale = v.Scale;
        var offset = v.Offset;

        v.Resize(1000, 700);

        Assert.Equal(scale, v.Scale, 7);
        Assert.Equal(offset, v.Offset);
    }

    [Theory]
    [MemberData(nameof(Matrix))]
    public void Same_video_reload_preserves_zoom(double imageW, double imageH, int orientation,
        double dpi, double viewW, double viewH)
    {
        var v = NewViewport(imageW, imageH, orientation, dpi, viewW, viewH, video: false);
        v.Zoom(new PointD(viewW / 2, viewH / 2), 1.2);
        double scale = v.Scale;

        v.Load("image", imageW, imageH, orientation, video: true);

        Assert.Equal(scale, v.Scale, 7);
    }

    [Theory]
    [MemberData(nameof(Matrix))]
    public void Image_switch_resets_to_fit(double imageW, double imageH, int orientation,
        double dpi, double viewW, double viewH)
    {
        var v = NewViewport(imageW, imageH, orientation, dpi, viewW, viewH, video: false);
        v.Zoom(new PointD(viewW / 2, viewH / 2), 2);

        v.Load("image", imageW, imageH, orientation, video: false);

        Assert.True(v.IsFit);
    }

    [Theory]
    [MemberData(nameof(Matrix))]
    public void New_video_resets_to_fit(double imageW, double imageH, int orientation,
        double dpi, double viewW, double viewH)
    {
        var v = NewViewport(imageW, imageH, orientation, dpi, viewW, viewH, video: true);
        v.Zoom(new PointD(viewW / 2, viewH / 2), 2);

        v.Load("new-video", imageW, imageH, orientation, video: true);
        Assert.True(v.IsFit);

        v.Zoom(new PointD(viewW / 2, viewH / 2), 2);
        v.Load("new-video", imageW + 1, imageH, orientation, video: true);
        Assert.True(v.IsFit);
    }

    /// <summary>WPF canvas reserves side/top chrome (344 / 160 DIP) before fitting.</summary>
    private static Viewport NewViewport(double imageW, double imageH, int orientation, double dpi,
        double viewW, double viewH, bool video)
    {
        var v = new Viewport();
        v.Resize(viewW / dpi - 344, viewH / dpi - 160);
        v.Load("image", imageW, imageH, orientation, video);
        return v;
    }
}
