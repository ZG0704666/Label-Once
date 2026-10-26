using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using Wpf.Ui.Controls;
using Button=System.Windows.Controls.Button;
using TextBox=Wpf.Ui.Controls.TextBox;
using TextBlock=System.Windows.Controls.TextBlock;
using MessageBoxButton=System.Windows.MessageBoxButton;
using MessageBoxResult=System.Windows.MessageBoxResult;
namespace LabelOnce.Desktop.Services;

public static class UserDialogs
{
    public static string? AnnotationCategory(IEnumerable<string> names,string selected)
    {
        var window=new FluentWindow{Title="确认类别",Width=420,SizeToContent=SizeToContent.Height,ResizeMode=ResizeMode.NoResize,WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow};
        var panel=new StackPanel{Margin=new Thickness(24)};
        panel.Children.Add(new TextBlock{Text="选择已有类别，或输入新类别",Margin=new Thickness(0,0,0,12)});
        var input=new ComboBox{IsEditable=true,IsTextSearchEnabled=true,ItemsSource=names.ToArray(),Text=selected,MinHeight=36};panel.Children.Add(input);
        var error=new TextBlock{TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,8,0,8)};panel.Children.Add(error);
        var actions=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right};
        var cancel=new Button{Content="取消",IsCancel=true};cancel.Click+=(_,_)=>window.DialogResult=false;actions.Children.Add(cancel);
        var ok=new Button{Content="确认",IsDefault=true};ok.Click+=(_,_)=>{if(string.IsNullOrWhiteSpace(input.Text)||input.Text.Contains('\n')||input.Text.Contains('\r')){error.Text="请输入有效类别名称";return;}window.DialogResult=true;};actions.Children.Add(ok);panel.Children.Add(actions);window.Content=panel;
        window.Loaded+=(_,_)=>input.Focus();return window.ShowDialog()==true?input.Text.Trim():null;
    }
    public static int ResolveCandidate()
    {
        var window=new FluentWindow{Title="尚未确认的标注",Width=560,SizeToContent=SizeToContent.Height,WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow,ResizeMode=ResizeMode.NoResize};
        var panel=new StackPanel{Margin=new Thickness(24)};panel.Children.Add(new TextBlock{Text="当前有未确认的轮廓或矩形。请选择如何处理。",TextWrapping=TextWrapping.Wrap});
        int result=0;foreach(var item in new[]{("确认类别并继续",1),("放弃预览",2),("留在当前图片",0)}){var button=new Button{Content=item.Item1,Margin=new Thickness(0,8,0,0)};button.Click+=(_,_)=>{result=item.Item2;window.DialogResult=true;};panel.Children.Add(button);}window.Content=panel;window.ShowDialog();return result;
    }
    public static string? AnnotationMethod(string selected)
    {
        var window=new FluentWindow{Title="选择标注方式",Width=520,SizeToContent=SizeToContent.Height,ResizeMode=ResizeMode.NoResize,WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow,Background=new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(29,35,43))};
        var panel=new StackPanel{Margin=new Thickness(24)};
        panel.Children.Add(new TextBlock{Text="为这个批次选择起步方式，之后可随时切换。",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,0,16)});
        string? result=null;
        foreach(var item in new[]{("手工标注","直接绘制框或多边形"),("SAM 辅助","人工点选或框选，Q/E 连续修正轮廓"),("YOLO 预标注","选择类别映射，批量生成检测框")})
        {
            var content=new StackPanel();content.Children.Add(new TextBlock{Text=item.Item1,FontWeight=FontWeights.SemiBold});content.Children.Add(new TextBlock{Text=item.Item2,TextWrapping=TextWrapping.Wrap,FontSize=12,Margin=new Thickness(0,4,0,0)});
            var button=new Button{Content=content,HorizontalContentAlignment=HorizontalAlignment.Left,Padding=new Thickness(14),Margin=new Thickness(0,0,0,8)};
            if(item.Item1==selected)button.Style=(Style)Application.Current.FindResource("Primary");
            button.Click+=(s,e)=>{result=item.Item1;window.DialogResult=true;};panel.Children.Add(button);
        }
        var cancel=new Button{Content="稍后选择",IsCancel=true,HorizontalAlignment=HorizontalAlignment.Right};cancel.Click+=(s,e)=>window.DialogResult=false;panel.Children.Add(cancel);window.Content=panel;
        return window.ShowDialog()==true?result:null;
    }
    public static string? Folder(string title)
    {
        var dialog=new OpenFolderDialog{Title=title};return dialog.ShowDialog()==true?dialog.FolderName:null;
    }
    public static string[] Files(string title,string filter="所有文件|*.*",bool multiple=false)
    {
        var dialog=new OpenFileDialog{Title=title,Filter=filter,Multiselect=multiple};return dialog.ShowDialog()==true?dialog.FileNames:[];
    }
    public static Dictionary<string,string>? Form(string title,Dictionary<string,string> values,bool multiline=false,string? explanation=null)
    {
        var window=new FluentWindow{Title=title,Width=620,Height=multiline?560:Math.Min(780,values.Count*64+170),WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow,Background=new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(29,35,43)),WindowBackdropType=WindowBackdropType.None};
        var root=new DockPanel{Margin=new Thickness(18)};
        var buttons=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right,Margin=new Thickness(0,12,0,0)};DockPanel.SetDock(buttons,Dock.Bottom);root.Children.Add(buttons);
        var cancel=new Button{Content="取消",MinWidth=90};cancel.Click+=(s,e)=>window.DialogResult=false;buttons.Children.Add(cancel);
        var ok=new Button{Content="保存 / 确认",MinWidth=110,Style=(Style)Application.Current.FindResource("Primary")};buttons.Children.Add(ok);
        var panel=new StackPanel();root.Children.Add(new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});
        if(explanation is not null)panel.Children.Add(new TextBlock{Text=explanation,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(3,0,3,16)});
        var editors=new Dictionary<string,TextBox>();
        foreach(var pair in values)
        {
            panel.Children.Add(new TextBlock{Text=pair.Key,Margin=new Thickness(3,8,3,2)});
            var box=new TextBox{Text=pair.Value,AcceptsReturn=multiline,MinHeight=multiline?260:34,VerticalScrollBarVisibility=multiline?ScrollBarVisibility.Auto:ScrollBarVisibility.Disabled,TextWrapping=multiline?TextWrapping.Wrap:TextWrapping.NoWrap};
            panel.Children.Add(box);editors[pair.Key]=box;
        }
        ok.Click+=(s,e)=>window.DialogResult=true;window.Content=root;
        return window.ShowDialog()==true?editors.ToDictionary(x=>x.Key,x=>x.Value.Text):null;
    }
    public static bool Confirm(string text)
    {
        var window=new FluentWindow{Title="Label Once",Width=520,SizeToContent=SizeToContent.Height,ResizeMode=ResizeMode.NoResize,WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow,Background=new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(29,35,43))};
        var panel=new StackPanel{Margin=new Thickness(24)};
        panel.Children.Add(new TextBlock{Text=text,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,8,0,24)});
        var actions=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right};
        var cancel=new Button{Content="取消",MinWidth=90,IsCancel=true};cancel.Click+=(s,e)=>window.DialogResult=false;
        var ok=new Button{Content="确认",MinWidth=90,IsDefault=true,Style=(Style)Application.Current.FindResource("Primary")};ok.Click+=(s,e)=>window.DialogResult=true;
        actions.Children.Add(cancel);actions.Children.Add(ok);panel.Children.Add(actions);window.Content=panel;
        return window.ShowDialog()==true;
    }
    public static Dictionary<string,object>? Parameters(string title,Dictionary<string,object> values)
    {
        var result=Form(title,values.ToDictionary(p=>p.Key,p=>JsonSerializer.Serialize(p.Value)),explanation:"数值直接填写；开关使用 true / false；字符串保留双引号。");
        return result?.ToDictionary(p=>p.Key,p=>(object)JsonSerializer.Deserialize<JsonElement>(p.Value));
    }
}
