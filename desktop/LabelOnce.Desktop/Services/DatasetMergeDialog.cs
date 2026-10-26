using System.Collections.ObjectModel;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using Wpf.Ui.Controls;
using Button=System.Windows.Controls.Button;
using CheckBox=System.Windows.Controls.CheckBox;
using ComboBox=System.Windows.Controls.ComboBox;
using TextBox=Wpf.Ui.Controls.TextBox;
using TextBlock=System.Windows.Controls.TextBlock;
using MessageBoxImage=System.Windows.MessageBoxImage;
using MessageBox=System.Windows.MessageBox;
using MessageBoxButton=System.Windows.MessageBoxButton;
namespace LabelOnce.Desktop.Services;

/// <summary>
/// 数据集整合对话框：登记多来源（本项目版本 / 跨项目版本 / 外部 YOLO 目录），先预览后提交。
/// 确认后返回 merge spec，由 ViewModel 以 dataset_merge 后台任务执行。
/// </summary>
public static class DatasetMergeDialog
{
    public static Dictionary<string, object>? DatasetSources(
        Func<string, object?, Task<JsonElement>> call, string project, string[] versions, string? activeVersion)
    {
        var window=new FluentWindow{Title="整合数据集",Width=760,Height=720,WindowStartupLocation=WindowStartupLocation.CenterOwner,
            Owner=Application.Current.MainWindow,ResizeMode=ResizeMode.CanMinimize,
            Background=new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(29,35,43)),WindowBackdropType=WindowBackdropType.None};
        var root=new DockPanel{Margin=new Thickness(18)};
        var buttons=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right,Margin=new Thickness(0,12,0,0)};
        DockPanel.SetDock(buttons,Dock.Bottom);root.Children.Add(buttons);
        var cancel=new Button{Content="取消",MinWidth=90};cancel.Click+=(_,_)=>window.DialogResult=false;buttons.Children.Add(cancel);
        var ok=new Button{Content="开始整合",MinWidth=110,Style=(Style)Application.Current.FindResource("Primary")};buttons.Children.Add(ok);

        var panel=new StackPanel();root.Children.Add(new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});
        panel.Children.Add(new TextBlock{Text="多来源智能整合：默认包含本项目素材（复选框可取消）；所有来源原有 train/val/test 划分作废，统一按比例与随机种子重新划分；同一图片按 SHA256 自动去重；类别按名称映射，只追加、既有 ID 永不位移；缺标签图片作为空标注负样本收录；基准集黑名单命中与其同组近邻固定进验证集；先预览确认，再原子写入新版本并自动激活。",
            TextWrapping=TextWrapping.Wrap,Margin=new Thickness(3,0,3,12)});

        var specs=new List<Dictionary<string,object>>();
        var shown=new ObservableCollection<string>();
        var list=new System.Windows.Controls.ListBox{ItemsSource=shown,MinHeight=110};
        panel.Children.Add(list);

        var sourceButtons=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(0,8,0,0)};
        Button SourceButton(string content)=>new(){Content=content,Margin=new Thickness(0,0,8,0),Padding=new Thickness(10,4,10,4)};
        void AddSource(Dictionary<string,object> spec,string label)
        {
            specs.Add(spec);
            var path=spec.TryGetValue("path",out var p)?p as string:null;
            var version=spec.TryGetValue("version",out var v)?v as string:null;
            var where=path is not null?$" · {path}":version is not null?$" · {version}":"";
            shown.Add(label+where+(path is not null&&version is not null?$" / {version}":""));
        }
        var cross=SourceButton("本机其它项目…");
        cross.Click+=async (_,_)=>{
            try{
                string? folder=Folder("选择其它项目的项目根目录");if(folder is null)return;
                var info=await call("dataset.merge.external_versions",new{external=folder});
                string[] available=info.TryGetProperty("versions",out var vs)
                    ?vs.EnumerateArray().Select(v=>v.GetString()!).ToArray():new string[0];
                if(available.Length==0){MessageBox.Show("该项目还没有任何数据集版本；请先在原项目创建并激活。","整合数据集");return;}
                string? active=info.TryGetProperty("active",out var av)&&av.ValueKind==JsonValueKind.String?av.GetString():null;
                var picked=Pick("选择要并入的数据集版本",available,active);
                if(picked is null)return;
                AddSource(new Dictionary<string,object>{["kind"]="cross_project",["path"]=folder,["version"]=picked},
                    $"其它项目 {System.IO.Path.GetFileName(folder.TrimEnd(System.IO.Path.DirectorySeparatorChar))}");
            }catch(Exception exc){MessageBox.Show(exc.Message,"整合数据集",MessageBoxButton.OK,MessageBoxImage.Warning);}
        };
        var external=SourceButton("外部 YOLO 目录…");
        external.Click+=(_,_)=>{
            string? folder=Folder("选择外部 YOLO 数据目录（images/ 与 labels/，附 dataset.yaml 类别表）");
            if(folder is null)return;
            AddSource(new Dictionary<string,object>{["kind"]="external_yolo",["path"]=folder},"外部 YOLO");
        };
        var internalVersion=SourceButton("本项目已有版本…");
        internalVersion.Click+=(_,_)=>{
            var remaining=versions.Where(v=>specs.All(s=>!string.Equals(s.GetValueOrDefault("version") as string,v,System.StringComparison.OrdinalIgnoreCase))).ToArray();
            if(remaining.Length==0){MessageBox.Show("项目内版本均已登记，无需重复添加。","整合数据集");return;}
            var picked=Pick("选择要并入的本项目版本",remaining,activeVersion);
            if(picked is null)return;
            AddSource(new Dictionary<string,object>{["kind"]="version",["version"]=picked},"项目版本");
        };
        var remove=SourceButton("移除选中");
        remove.Click+=(_,_)=>{var i=list.SelectedIndex;if(i>=0&&i<specs.Count){specs.RemoveAt(i);shown.RemoveAt(i);}};
        var ownMaterial=new CheckBox{Content="包含本项目素材（默认勾选：只收录已完成复核的样本，待核/已驳回不进）",IsChecked=true,
            ToolTip="所有来源（含本项目素材）原有划分一律作废，统一重新划分",Margin=new Thickness(3,8,0,4)};
        panel.Children.Add(ownMaterial);
        sourceButtons.Children.Add(cross);sourceButtons.Children.Add(external);sourceButtons.Children.Add(internalVersion);sourceButtons.Children.Add(remove);
        panel.Children.Add(sourceButtons);

        panel.Children.Add(new TextBlock{Text="训练比例",Margin=new Thickness(3,16,3,2)});
        var ratioTrain=new TextBox{Text="0.8"};
        panel.Children.Add(new TextBlock{Text="验证比例",Margin=new Thickness(3,8,3,2)});
        var ratioVal=new TextBox{Text="0.2"};
        panel.Children.Add(new TextBlock{Text="测试比例（默认 0，只分训练与验证）",Margin=new Thickness(3,8,3,2)});
        var ratioTest=new TextBox{Text="0"};
        panel.Children.Add(new TextBlock{Text="随机种子",Margin=new Thickness(3,8,3,2)});
        var seed=new TextBox{Text="42"};
        panel.Children.Add(new TextBlock{Text="同名冲突取舍（同名不同内容的图片保留哪一份）",Margin=new Thickness(3,12,3,2)});
        var dedup=new ComboBox{ItemsSource=new[]{"先登记优先","后加入优先"},SelectedIndex=1};
        var keepSegment=new CheckBox{Content="保留多边形行（>5 字段标签）",IsChecked=true,Margin=new Thickness(3,12,0,0)};
        var acceptNew=new CheckBox{Content="接受来源中的新类别（追加到类别表末尾，不改动既有 ID）",IsChecked=true,Margin=new Thickness(3,8,0,0)};
        panel.Children.Add(dedup);panel.Children.Add(keepSegment);panel.Children.Add(acceptNew);
        panel.Children.Add(new TextBlock{Text="基准集黑名单（golden 目录 / manifest.csv / dataset.yaml / 单图；命中样本与其同组近邻帧固定进验证集）",
            TextWrapping=TextWrapping.Wrap,Margin=new Thickness(3,12,3,2)});
        var blacklistRow=new DockPanel{LastChildFill=true};
        var browse=new Button{Content="浏览…",Padding=new Thickness(10,4,10,4)};
        var blacklist=new TextBox{Text=""};
        browse.Click+=(_,_)=>{var f=Open("选择黑名单来源","黑名单|*.csv;*.yaml;*.yml;*.jpg;*.jpeg;*.png|黑名单目录|*.*");if(f.Length>0)blacklist.Text=f[0];};
        DockPanel.SetDock(browse,Dock.Right);blacklistRow.Children.Add(browse);blacklistRow.Children.Add(blacklist);
        panel.Children.Add(blacklistRow);

        panel.Children.Add(new TextBlock{Text="预览（只读，不写任何文件）",Margin=new Thickness(3,16,3,2)});
        var previewButton=new Button{Content="计算预览",HorizontalAlignment=HorizontalAlignment.Left,Padding=new Thickness(12,4,12,4)};
        panel.Children.Add(previewButton);
        var previewBox=new System.Windows.Controls.TextBox{IsReadOnly=true,AcceptsReturn=true,Height=210,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,
            TextWrapping=TextWrapping.Wrap,FontFamily=new System.Windows.Media.FontFamily("Consolas"),FontSize=12,Margin=new Thickness(3,8,0,0)};
        panel.Children.Add(previewBox);
        Dictionary<string, object>? okSpec=null;

        Dictionary<string,object> BuildSpec()
        {
            var sourceList=new List<Dictionary<string,object>>();
            if(ownMaterial.IsChecked==true)sourceList.Add(new Dictionary<string,object>{["kind"]="project"});
            sourceList.AddRange(specs);
            if(sourceList.Count==0)throw new InvalidOperationException("请至少登记一个数据来源，或勾选包含本项目素材");
            var ratios=new[]{ParseRatio(ratioTrain.Text,"训练"),ParseRatio(ratioVal.Text,"验证"),ParseRatio(ratioTest.Text,"测试")};
            if(Math.Abs(ratios.Sum()-1)>1e-6)throw new InvalidOperationException("训练/验证/测试比例之和必须为 1");
            var spec=new Dictionary<string,object>{["sources"]=sourceList.ToArray(),
                ["ratios"]=ratios,["seed"]=int.Parse(string.IsNullOrWhiteSpace(seed.Text)?"42":seed.Text.Trim()),
                ["dedup"]=dedup.SelectedIndex==0?"first":"last",
                ["keep_segment"]=keepSegment.IsChecked==true,["accept_new_classes"]=acceptNew.IsChecked==true};
            if(!string.IsNullOrWhiteSpace(blacklist.Text))spec["blacklist"]=blacklist.Text.Trim();
            return spec;
        }
        previewButton.Click+=async (_,_)=>{
            previewButton.IsEnabled=false;previewBox.Text="正在计算预览…";
            try{previewBox.Text=new StudioReportFormatter().Format(await call("dataset.merge.preview",new{project,spec=BuildSpec()}));}
            catch(Exception exc){previewBox.Text="预览失败：\n"+exc.Message;}
            finally{previewButton.IsEnabled=true;}
        };
        ok.Click+=(_,_)=>{
            try{okSpec=BuildSpec();window.DialogResult=true;}
            catch(Exception exc){MessageBox.Show(exc.Message,"整合数据集",MessageBoxButton.OK,MessageBoxImage.Warning);}
        };
        window.Content=root;
        return window.ShowDialog()==true?okSpec:null;
    }

    static double ParseRatio(string text,string label)
    {
        text=text.Trim().TrimEnd('%');
        if(!double.TryParse(text,out var value))throw new InvalidOperationException($"{label}比例不是数值");
        if(value<0||value>1)throw new InvalidOperationException($"{label}比例必须在 0 到 1 之间");
        return value;
    }

    static string? Folder(string title)
    {
        var dialog=new OpenFolderDialog{Title=title};return dialog.ShowDialog()==true?dialog.FolderName:null;
    }

    static string[] Open(string title,string filter)
    {
        var dialog=new OpenFileDialog{Title=title,Filter=filter};return dialog.ShowDialog()==true?dialog.FileNames:[];
    }

    static string? Pick(string title,IReadOnlyList<string> names,string? selected)
    {
        var window=new FluentWindow{Title=title,Width=460,SizeToContent=SizeToContent.Height,WindowStartupLocation=WindowStartupLocation.CenterOwner,Owner=Application.Current.MainWindow,
            Background=new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(29,35,43))};
        var panel=new StackPanel{Margin=new Thickness(24)};
        panel.Children.Add(new TextBlock{Text="选择数据集版本",Margin=new Thickness(0,0,0,12)});
        var combo=new ComboBox{ItemsSource=names,SelectedIndex=Math.Max(0,IndexOf(names,selected)),MinHeight=36};panel.Children.Add(combo);
        string? result=null;
        var actions=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right,Margin=new Thickness(0,12,0,0)};
        var cancel=new Button{Content="取消",IsCancel=true};cancel.Click+=(_,_)=>window.DialogResult=false;actions.Children.Add(cancel);
        var ok=new Button{Content="确认",IsDefault=true,Style=(Style)Application.Current.FindResource("Primary"),Margin=new Thickness(8,0,0,0)};
        ok.Click+=(_,_)=>{result=combo.SelectedItem as string;window.DialogResult=true;};actions.Children.Add(ok);panel.Children.Add(actions);
        window.Content=panel;
        return window.ShowDialog()==true?result:null;
        static int IndexOf(IReadOnlyList<string> names,string? selected)
        {
            for(var k=0;k<names.Count;k++)if(string.Equals(names[k],selected,System.StringComparison.OrdinalIgnoreCase))return k;
            return 0;
        }
    }
}

/// <summary>把 dataset.merge.preview 的报告渲染成中文文本。</summary>
public sealed class StudioReportFormatter
{
    public string Format(JsonElement report)
    {
        var lines=new List<string>();
        lines.Add($"样本总数：{Int(report,"total")} · 类别 {Count(report,"names")} 个");
        if(report.TryGetProperty("new_classes",out var newClasses)&&newClasses.GetArrayLength()>0)
            lines.Add($"新增类别：{Join(newClasses)}（将追加到类别表末尾）");
        var estimate=report.TryGetProperty("estimate",out var est)?est:default;
        if(estimate.ValueKind!=JsonValueKind.Undefined&&estimate.TryGetProperty("by_split",out var by))
            lines.Add($"分布：train {Int(by,"train")} / val {Int(by,"val")} / test {Int(by,"test")}");
        if(report.TryGetProperty("dedupe",out var dedupe))
            lines.Add($"去重：与其它来源完全重复 {Int(dedupe,"duplicates")} 张 · 同图异标签 {Int(dedupe,"content_clash_count")} 组");
        if(report.TryGetProperty("blacklist",out var pin))
            lines.Add($"基准集黑名单：命中 {Int(pin,"hits")} 张，连同同组近邻共 {Int(pin,"pinned_samples")} 张固定进 val");
        if(report.TryGetProperty("conflicts",out var conflicts))
        {
            if(conflicts.TryGetProperty("blocks",out var blocks))
                foreach(var block in blocks.EnumerateArray())
                    lines.Add($"【阻断】[{block.GetProperty("code").GetString()}] {block.GetProperty("message").GetString()}");
            if(conflicts.TryGetProperty("warnings",out var warnings))
                foreach(var warn in warnings.EnumerateArray())
                    lines.Add($"【提示】[{warn.GetProperty("code").GetString()}] {warn.GetProperty("message").GetString()}");
        }
        if(report.TryGetProperty("per_source",out var sources))
        {
            lines.Add("");
            foreach(var src in sources.EnumerateArray())
                lines.Add($"· {Text(src,"source")}：{Int(src,"samples")} 张，落库 {Int(src,"contributed")}，去重 {Int(src,"deduped")}"
                    +(Int(src,"empty_labels")>0?$"，空标注负样本 {Int(src,"empty_labels")}":"")
                    +(Int(src,"skipped")>0?$"，缺标签跳过 {Int(src,"skipped")}":""));
        }
        lines.Add("");
        lines.Add("没有【阻断】即可开始整合；【提示】项会记录进版本清单。");
        return string.Join('\n',lines);

        static string Join(JsonElement array)=>string.Join("、",array.EnumerateArray().Select(n=>n.GetString()));
        static string Text(JsonElement e,string key)=>e.TryGetProperty(key,out var v)&&v.ValueKind==JsonValueKind.String?v.GetString()!:"";
        static int Int(JsonElement e,string key)=>e.TryGetProperty(key,out var v)&&v.TryGetInt32(out var i)?i:0;
        static int Count(JsonElement e,string key)=>e.TryGetProperty(key,out var v)?v.GetArrayLength():0;
    }
}
