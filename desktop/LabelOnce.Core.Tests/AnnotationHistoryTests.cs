using LabelOnce.Core;
using Xunit;

namespace LabelOnce.Core.Tests;

/// <summary>Port of the former console harness's AnnotationHistory block.</summary>
public class AnnotationHistoryTests
{
    private static Annotation Box(double x1, double y1, double x2, double y2, int targetId = 7) => new()
    {
        X1 = x1, Y1 = y1, X2 = x2, Y2 = y2,
        Polygons = [[new[] { .1, .2 }, new[] { .4, .2 }, new[] { .4, .6 }]],
        TargetId = targetId,
    };

    [Fact]
    public void Undo_restores_previous_bounds_polygons_and_target_id()
    {
        var box = Box(.1, .2, .4, .6);
        var history = new AnnotationHistory();
        history.Reset([box]);

        box.SetBounds(.2, .3, .8, .9);
        history.Record([box]);

        var undone = history.Step(-1)!;
        Assert.Equal(.1, undone[0].Polygons![0][0][0], 7);
        Assert.Equal(7, undone[0].TargetId);
    }

    [Fact]
    public void Redo_reapplies_the_edited_bounds()
    {
        var box = Box(.1, .2, .4, .6);
        var history = new AnnotationHistory();
        history.Reset([box]);
        box.SetBounds(.2, .3, .8, .9);
        history.Record([box]);
        history.Step(-1);

        var redone = history.Step(1)!;
        Assert.Equal(.8, redone[0].Polygons![0][1][0], 7);
    }

    [Fact]
    public void Recording_after_an_undo_clears_the_redo_stack()
    {
        var box = Box(.1, .2, .4, .6);
        var history = new AnnotationHistory();
        history.Reset([box]);
        box.SetBounds(.2, .3, .8, .9);
        history.Record([box]);
        history.Step(-1);

        history.Record([]);

        Assert.Null(history.Step(1));
    }
}
