using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace LabelOnce.Desktop.Controls;

public sealed record TrainingEpoch(int Epoch, double BoxLoss, double Map50);

public sealed class TrainingCurve : FrameworkElement
{
    private static readonly Pen AxisPen = FreezePen(new Pen(new SolidColorBrush(Color.FromRgb(70, 80, 92)), 1));
    private static readonly Pen GridPen = FreezePen(new Pen(new SolidColorBrush(Color.FromRgb(55, 65, 75)), 1)
    {
        DashStyle = new DashStyle([4, 4], 0)
    });
    private static readonly Brush LossBrush = FreezeBrush(255, 177, 86);
    private static readonly Brush MapBrush = FreezeBrush(66, 217, 234);
    private static readonly Brush TipBrush = FreezeBrush(20, 27, 34);

    public static readonly DependencyProperty EpochsProperty = DependencyProperty.Register(
        nameof(Epochs),
        typeof(IReadOnlyList<TrainingEpoch>),
        typeof(TrainingCurve),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender));

    public IReadOnlyList<TrainingEpoch>? Epochs
    {
        get => (IReadOnlyList<TrainingEpoch>?)GetValue(EpochsProperty);
        set => SetValue(EpochsProperty, value);
    }

    static TrainingCurve()
    {
        CursorProperty.OverrideMetadata(typeof(TrainingCurve), new FrameworkPropertyMetadata(Cursors.Cross));
    }

    public TrainingCurve()
    {
        Focusable = false;
    }

    private static Pen FreezePen(Pen pen)
    {
        pen.Freeze();
        return pen;
    }

    private static SolidColorBrush FreezeBrush(byte r, byte g, byte b)
    {
        var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
        brush.Freeze();
        return brush;
    }

    private static Pen Thin(Brush brush, double width)
    {
        var pen = new Pen(brush, width);
        pen.Freeze();
        return pen;
    }

    private static FormattedText CreateText(string text, double size, Brush brush, double dpi)
    {
        var typeface = new Typeface("Segoe UI");
        return new FormattedText(
            text,
            CultureInfo.CurrentCulture,
            FlowDirection.LeftToRight,
            typeface,
            size,
            brush,
            dpi);
    }

    private static Point ToPlotPoint(Rect plot, int epoch, double value, double min, double max)
    {
        if (max <= min)
        {
            return new Point(plot.Left, plot.Bottom);
        }

        var normalized = (value - min) / (max - min);
        var x = plot.Left + plot.Width * (epoch - 1) / Math.Max(1, epoch - 1);
        var y = plot.Bottom - plot.Height * Math.Clamp(normalized, 0, 1);
        return new Point(x, y);
    }

    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);

        var dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip;
        var dim = FreezeBrush(156, 171, 184);
        var textLoss = CreateText("验证框损失", 12, LossBrush, dpi);
        var textMap = CreateText("mAP50", 12, MapBrush, dpi);
        dc.DrawText(textLoss, new Point(8, 6));
        dc.DrawText(textMap, new Point(96, 6));

        var rows = Epochs;
        var plot = new Rect(46, 26, Math.Max(1, ActualWidth - 46 - 56), Math.Max(1, ActualHeight - 26 - 24));

        if (rows is not { Count: > 0 })
        {
            dc.DrawRectangle(Brushes.Transparent, null, new Rect(plot.X - 8, plot.Y - 4, plot.Width + 64, plot.Height + 8));
            var hint = CreateText("训练开始后实时显示曲线", 13, dim, dpi);
            dc.DrawText(hint, new Point(plot.X + plot.Width / 2 - 92, plot.Y + plot.Height / 2 - 10));
            return;
        }

        var losses = rows.Select(r => r.BoxLoss).Where(double.IsFinite).ToArray();
        double lossMax = losses.Length > 0 ? Math.Max(0.01, losses.Max() * 1.1) : 1;
        lossMax = Math.Ceiling(lossMax * 100) / 100;
        double lossMin = losses.Length > 0 ? Math.Max(0, losses.Min() * 0.9) : 0;
        int maxEpoch = Math.Max(2, rows.Max(r => r.Epoch));

        for (int i = 0; i <= 4; i++)
        {
            double y = plot.Top + plot.Height * i / 4;
            dc.DrawLine(GridPen, new Point(plot.Left, y), new Point(plot.Right, y));
            double v = lossMin + (lossMax - lossMin) * (1 - i / 4d);
            var tick = CreateText(v.ToString("0.##"), 10, dim, dpi);
            dc.DrawText(tick, new Point(plot.Left - tick.Width - 5, y - tick.Height / 2));
            double m = 1 - i / 4d;
            var mapTick = CreateText(m.ToString("0.0"), 10, dim, dpi);
            dc.DrawText(mapTick, new Point(plot.Right + 5, y - mapTick.Height / 2));
        }

        int step = Math.Max(1, (int)Math.Ceiling(maxEpoch / 6d));
        for (int e = 1; e <= maxEpoch; e += step)
        {
            double x = plot.Left + plot.Width * (e - 1) / Math.Max(1, maxEpoch - 1);
            dc.DrawLine(AxisPen, new Point(x, plot.Bottom), new Point(x, plot.Bottom + 3));
            var tick = CreateText(e.ToString(), 10, dim, dpi);
            dc.DrawText(tick, new Point(x - tick.Width / 2, plot.Bottom + 4));
        }

        dc.DrawLine(AxisPen, new Point(plot.Left, plot.Top), new Point(plot.Left, plot.Bottom));
        dc.DrawLine(AxisPen, new Point(plot.Right, plot.Top), new Point(plot.Right, plot.Bottom));
        dc.DrawLine(AxisPen, new Point(plot.Left, plot.Bottom), new Point(plot.Right, plot.Bottom));

        Point Map(int epoch, double value, double lo, double hi)
        {
            if (hi <= lo)
            {
                return new Point(plot.Left, plot.Bottom);
            }

            var x = plot.Left + plot.Width * (epoch - 1) / Math.Max(1, maxEpoch - 1);
            var y = plot.Bottom - plot.Height * Math.Clamp((value - lo) / (hi - lo), 0, 1);
            return new Point(x, y);
        }

        void Series(Func<TrainingEpoch, double> get, Brush brush, double lo, double hi)
        {
            var pts = new List<Point>();
            foreach (var row in rows)
            {
                double v = get(row);
                if (double.IsFinite(v))
                {
                    pts.Add(Map(row.Epoch, v, lo, hi));
                }
            }

            if (pts.Count == 0)
            {
                return;
            }

            if (pts.Count == 1)
            {
                dc.DrawEllipse(brush, null, pts[0], 3, 3);
                return;
            }

            var geo = new StreamGeometry();
            using (var ctx = geo.Open())
            {
                ctx.BeginFigure(pts[0], false, false);
                for (int i = 0; i < pts.Count - 1; i++)
                {
                    var p0 = pts[Math.Max(0, i - 1)];
                    var p1 = pts[i];
                    var p2 = pts[i + 1];
                    var p3 = pts[Math.Min(pts.Count - 1, i + 2)];
                    var c1 = new Point(p1.X + (p2.X - p0.X) / 6, p1.Y + (p2.Y - p0.Y) / 6);
                    var c2 = new Point(p2.X - (p3.X - p1.X) / 6, p2.Y - (p3.Y - p1.Y) / 6);
                    ctx.BezierTo(c1, c2, p2, true, false);
                }
                ctx.Close();
            }
            geo.Freeze();
            dc.DrawGeometry(null, Thin(brush, 2), geo);
            foreach (var p in pts)
            {
                dc.DrawEllipse(brush, null, p, 2.5, 2.5);
            }
        }

        Series(r => r.BoxLoss, LossBrush, lossMin, lossMax);
        Series(r => r.Map50, MapBrush, 0, 1);

        var last = rows[^1];
        string tail = $"{last.Epoch}轮 · 损失 {last.BoxLoss:F3} · mAP50 {last.Map50:P1}";
        var tailText = CreateText(tail, 11, dim, dpi);
        dc.DrawText(tailText, new Point(Math.Max(plot.Left, plot.Right - tailText.Width), plot.Bottom + 4));

        if (hover is { } hp && hp.X >= plot.Left && hp.X <= plot.Right)
        {
            double frac = (hp.X - plot.Left) / plot.Width;
            int idx = Math.Clamp((int)Math.Round(frac * (maxEpoch - 1)), 0, rows.Count - 1);
            var row = rows[idx];
            var px = Map(row.Epoch, row.BoxLoss, lossMin, lossMax);
            var py = Map(row.Epoch, row.Map50, 0, 1);
            dc.DrawLine(GridPen, new Point(px.X, plot.Top), new Point(px.X, plot.Bottom));
            dc.DrawEllipse(TipBrush, new Pen(LossBrush, 2), px, 4, 4);
            dc.DrawEllipse(TipBrush, new Pen(MapBrush, 2), py, 4, 4);

            string info = $"轮 {row.Epoch}  损失 {row.BoxLoss:F3}  mAP50 {row.Map50:P1}";
            var box = CreateText(info, 11, dim, dpi);
            double bw = box.Width + 16;
            double bx = Math.Min(Math.Max(hp.X - bw / 2, plot.Left), plot.Right - bw);
            var rect = new Rect(bx, plot.Top + 2, bw, box.Height + 8);
            dc.DrawRoundedRectangle(TipBrush, new Pen(dim, 1), rect, 5, 5);
            dc.DrawText(box, new Point(rect.X + 8, rect.Y + 4));
        }
    }

    private Point? hover;

    protected override void OnMouseMove(MouseEventArgs e)
    {
        if (Epochs is { Count: > 0 })
        {
            hover = e.GetPosition(this);
            InvalidateVisual();
        }
    }

    protected override void OnMouseLeave(MouseEventArgs e)
    {
        if (hover is not null)
        {
            hover = null;
            InvalidateVisual();
        }
    }
}
