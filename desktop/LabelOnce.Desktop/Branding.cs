using System.IO;

namespace LabelOnce.Desktop;

/// <summary>Single source of truth for user-visible product identity strings.</summary>
/// <remarks>
/// The product display name and the on-disk log file name are intentionally separated:
/// the display name is rebrandable via settings (the backend stores a "brand" preference),
/// whereas the log file name must stay stable so support can always find it. Change the
/// display name here rather than editing individual windows/dialogs.
/// </remarks>
public static class Branding
{
    /// <summary>Default product display name shown in window titles and dialogs.</summary>
    public const string ProductName = "Label Once";

    /// <summary>Stable file name (without extension) for the WPF crash log in %TEMP%.</summary>
    public const string LogFileName = "LabelOnce-WPF.log";

    /// <summary>Full path to the WPF crash log.</summary>
    public static string LogFilePath => Path.Combine(Path.GetTempPath(), LogFileName);
}
