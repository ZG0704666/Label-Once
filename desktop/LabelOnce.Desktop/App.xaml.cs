using System.IO;
using System.Windows;
namespace LabelOnce.Desktop;
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException+=(s,args)=>{ File.AppendAllText(Branding.LogFilePath,args.Exception+Environment.NewLine); MessageBox.Show(args.Exception.Message,Branding.ProductName);args.Handled=true; };
    }
}
