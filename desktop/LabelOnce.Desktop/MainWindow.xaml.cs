using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using LabelOnce.Desktop.ViewModels;
using Wpf.Ui.Controls;
using Microsoft.Win32;
namespace LabelOnce.Desktop;
public partial class MainWindow : FluentWindow
{
    readonly StudioViewModel vm=new();
    bool syncing,focus,manualSidebar,closing;
    bool confirmingCandidate;
    double sidebarWidth=280;
    public MainWindow():this(true) { }
    public MainWindow(bool openCommandLineProject)
    {
        InitializeComponent();DataContext=vm;LibraryCanvas.ReadOnly=true;
        vm.ResolveCandidate=ResolveCandidate;
        Canvas.CandidateReady+=candidate=>{ _ = vm.Safe(async()=>{ await ConfirmCandidate(); }); };
        PreviewKeyDown+=WindowKeyDown;
        vm.GetBoxes=()=>Canvas.Boxes.Select(b=>b.Copy()).ToList();vm.GetNextId=()=>Canvas.NextTargetId;vm.GetSamLabel=()=>Canvas.Mode=="sam-negative"?0:1;Canvas.SamStateChanged+=(state,infer)=>_=vm.Safe(()=>vm.SetSamState(state,infer));Canvas.NewTarget+=vm.NewSamTarget;Canvas.ModeChanged+=mode=>{if(mode.StartsWith("sam")||mode=="roi")vm.AnnotationMethod="SAM 辅助";};
        vm.DocumentChanged+=doc=>
        {
            syncing=true;
            vm.CurrentSourcePath=doc.Source;
            try{Canvas.Classes=LibraryCanvas.Classes=vm.Classes.ToArray();Canvas.Load(doc.Path,doc.Source,doc.Width,doc.Height,doc.Orientation,doc.Boxes,doc.Video);LibraryCanvas.Load(doc.Path,doc.Source,doc.Width,doc.Height,doc.Orientation,doc.Boxes,doc.Video);}
            finally{syncing=false;}
            VideoBar.Visibility=doc.Video?Visibility.Visible:Visibility.Collapsed;
            UpdateReadOnly();
        };
        vm.CanvasAction+=CanvasAction;vm.PageRequested+=ShowPage;vm.MaterialChanged+=ApplyMaterial;
        vm.PropertyChanged+=(s,e)=>{if(e.PropertyName is nameof(vm.Busy) or nameof(vm.VideoState) or nameof(vm.Saving))UpdateReadOnly();if(e.PropertyName==nameof(vm.AnnotationMethod)){if(vm.AnnotationMethod=="SAM 辅助"&&!Canvas.Mode.StartsWith("sam")&&Canvas.Mode!="roi")_=vm.Safe(()=>ChangeMode("sam-point"));else if(vm.AnnotationMethod!="SAM 辅助"&&(Canvas.Mode.StartsWith("sam")||Canvas.Mode=="roi"))_=vm.Safe(()=>ChangeMode("select"));}if(e.PropertyName==nameof(vm.Brand))Title=vm.Brand;if(e.PropertyName==nameof(vm.LogoPath))ApplyLogo();};
        Canvas.Changed+=()=>{if(!syncing)vm.AnnotationChanged();};
        Canvas.EditStarted+=vm.InvalidateSamRequests;
        Canvas.SelectionChanged+=()=>{if(syncing)return;syncing=true;try{ObjectList.SelectedIndex=Canvas.Selected;}finally{syncing=false;}};
        Canvas.Navigate+=step=>_=vm.Safe(()=>vm.Navigate(step));Canvas.Confirm+=()=>_=vm.Safe(vm.ConfirmNext);
        Canvas.ViewChanged+=()=>vm.ViewStatus=Canvas.View.IsFit?"适配":"手动";
        Loaded+=async(s,e)=>{ApplyMaterial();await vm.Initialize();var args=Environment.GetCommandLineArgs();if(openCommandLineProject&&args.Length>1&&Directory.Exists(args[1]))await vm.Safe(()=>vm.OpenProject(args[1]));else if(!vm.ShowHomeAtStartup)vm.Go(StudioViewModel.PageLibrary);};
        SizeChanged+=(s,e)=>UpdateSidebar();Deactivated+=(s,e)=>Canvas.StopNavigation();Closing+=OnClosing;
        SystemEvents.UserPreferenceChanged+=(s,e)=>Dispatcher.BeginInvoke(ApplyMaterial);
    }
    void UpdateReadOnly(){Canvas.ReadOnly=vm.Saving||(vm.Busy&&vm.VideoState!="paused");if(vm.Busy)Canvas.StopNavigation();}
    void ShowPage(int page)
    {
        Canvas.StopNavigation();var pages=new FrameworkElement[]{HomePage,LibraryPage,AnnotationPage,TrainingPage,ModelPage,SettingsPage};
        for(int i=0;i<pages.Length;i++)pages[i].Visibility=i==page?Visibility.Visible:Visibility.Collapsed;
        ProjectToolbar.Visibility=page==StudioViewModel.PageAnnotation||focus?Visibility.Collapsed:Visibility.Visible;
        ProjectToolbarRow.Height=new GridLength(page==StudioViewModel.PageAnnotation||focus?0:44);
        if(page==StudioViewModel.PageAnnotation)Canvas.Refocus();UpdateSidebar();
    }
    void CanvasAction(string action)
    {
        switch(action)
        {
            case "replace-candidate":Canvas.SetBoxes(vm.PendingSam);break;
            case "update-sam":Canvas.UpdateSam(vm.PendingSam);break;
            case "sam-finish":_=vm.Safe(async()=>{await ConfirmCandidate();});break;
            case "sam-new":_=vm.Safe(async()=>{if(await ConfirmCandidate())Canvas.NewSam();});break;
            case "sam-clear":Canvas.ClearSam();break;
            case "fit":Canvas.Fit();break;
            case "delete":Canvas.Delete();break;
            case "undo":Canvas.Undo(-1);break;
            case "redo":Canvas.Undo(1);break;
            case "clear-ai":Canvas.SetBoxes(Canvas.Boxes.Where(b=>b.Origin!="AI"));break;
            case "apply-sam":{bool locked=Canvas.ReadOnly;Canvas.ReadOnly=false;Canvas.Add(vm.PendingSam);Canvas.ReadOnly=locked;break;}
            case "tracking-targets":Canvas.SetBoxes(vm.PendingSam,false);vm.SyncObjects();break;
            case "tracking-next-id":Canvas.NextTargetId=Math.Max(Canvas.NextTargetId,vm.TrackingNextId);break;
            case "stop-navigation":Canvas.StopNavigation();break;
            case "clear-document":vm.CurrentSourcePath="Label Once";Canvas.Clear();LibraryCanvas.Clear();VideoBar.Visibility=Visibility.Collapsed;break;
            default:_=vm.Safe(()=>ChangeMode(action));break;
        }
    }
    void ApplyMaterial()
    {
        using var key=Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
        bool transparency=Convert.ToInt32(key?.GetValue("EnableTransparency",1))!=0;
        bool enabled=vm.Acrylic&&transparency&&!SystemParameters.HighContrast&&Environment.OSVersion.Version.Build>=22000;
        WindowBackdropType=enabled?WindowBackdropType.Mica:WindowBackdropType.None;
        // Mica：约 88% 不透明深底，保留极淡的系统底纹；回退时完全不透明，保证亮壁纸下的对比度。
        Background=new SolidColorBrush(enabled?Color.FromArgb(0xE1,0x16,0x1B,0x21):Color.FromRgb(0x16,0x1B,0x21));
    }
    async Task ChangeMode(string mode)
    {
        bool samMode=mode.StartsWith("sam")||mode=="roi";
        bool currentSam=Canvas.Mode.StartsWith("sam")||Canvas.Mode=="roi";
        if(Canvas.HasDraft&&mode!=Canvas.Mode&&!(samMode&&currentSam)&&!await ResolveCandidate())return;
        Canvas.SetMode(mode);
    }
    async Task<bool> ConfirmCandidate()
    {
        if(confirmingCandidate)return false;
        confirmingCandidate=true;Canvas.IsHitTestVisible=false;
        try
        {
            while(vm.SamWorking)await Task.Delay(30);
            if(!Canvas.HasCandidate)return !Canvas.HasDraft;
            var name=Services.UserDialogs.AnnotationCategory(vm.Classes,vm.SelectedClass>=0&&vm.SelectedClass<vm.Classes.Count?vm.Classes[vm.SelectedClass]:"");
            if(name is null)return false;
            var id=await vm.EnsureClass(name);Canvas.Classes=vm.Classes.ToArray();Canvas.CommitCandidate(id);return true;
        }
        finally{confirmingCandidate=false;Canvas.IsHitTestVisible=true;Canvas.Refocus();}
    }
    async Task<bool> ResolveCandidate()
    {
        if(!Canvas.HasDraft&&!vm.SamWorking)return true;
        if(confirmingCandidate)return false;
        var choice=Services.UserDialogs.ResolveCandidate();
        if(choice==1)return await ConfirmCandidate();
        if(choice==2){vm.InvalidateSamRequests();Canvas.DiscardCandidate();return true;}
        return false;
    }
    static bool InTextInput(DependencyObject? source)
    {
        while (source is not null)
        {
            if (source is System.Windows.Controls.Primitives.TextBoxBase or System.Windows.Controls.ComboBox or System.Windows.Controls.PasswordBox) return true;
            source = System.Windows.Media.VisualTreeHelper.GetParent(source);
        }
        return false;
    }
    void WindowKeyDown(object sender,KeyEventArgs e)
    {
        if(vm.Page!=StudioViewModel.PageAnnotation||confirmingCandidate||Keyboard.Modifiers!=ModifierKeys.None)return;
        if(InTextInput(e.OriginalSource as DependencyObject))return;
        if(e.Key is Key.A or Key.D)
        {
            _=vm.Safe(()=>vm.Navigate(e.Key==Key.A?-1:1));
            e.Handled=true;
            return;
        }
        string? mode=e.Key switch{Key.Q=>"sam-point",Key.E=>"sam-negative",Key.W=>"draw",Key.P=>"polygon",_=>null};
        if(mode is not null){_=vm.Safe(()=>ChangeMode(mode));e.Handled=true;}

    }
    void ApplyLogo()
    {
        try
        {
            string source=File.Exists(vm.LogoPath)?vm.LogoPath:"pack://application:,,,/logo.png"; // 未配置时使用内置产品 LOGO
            using var stream=Application.GetResourceStream(new Uri(source,UriKind.Absolute)) is { } rs?rs.Stream:File.OpenRead(source);
            Icon=System.Windows.Media.Imaging.BitmapFrame.Create(stream,System.Windows.Media.Imaging.BitmapCreateOptions.None,System.Windows.Media.Imaging.BitmapCacheOption.OnLoad);
        }
        catch(IOException){vm.Status="图标无法读取，请重新选择";}
        catch(NotSupportedException){vm.Status="不支持的图标格式";}
    }
    void UpdateSidebar()
    {
        bool show=!focus&&(ActualWidth>=1000||manualSidebar);
        if(!show&&SidebarColumn.ActualWidth>0)sidebarWidth=SidebarColumn.ActualWidth;
        SidebarColumn.Width=show?new GridLength(sidebarWidth):new GridLength(0);SidebarSplitterColumn.Width=new GridLength(show?6:0);
        Sidebar.Visibility=SidebarSplitter.Visibility=show?Visibility.Visible:Visibility.Collapsed;
    }
    void ToggleSidebar(object sender,RoutedEventArgs e)
    {
        if(Sidebar.Visibility==Visibility.Visible){focus=true;manualSidebar=false;}else{focus=false;manualSidebar=true;}UpdateSidebar();
    }
    void ToggleFocus(object sender,RoutedEventArgs e){focus=!focus;ProjectToolbar.Visibility=focus||vm.Page==StudioViewModel.PageAnnotation?Visibility.Collapsed:Visibility.Visible;ProjectToolbarRow.Height=new GridLength(focus||vm.Page==StudioViewModel.PageAnnotation?0:44);UpdateSidebar();Canvas.Refocus();}
    void ToggleLogs(object sender,RoutedEventArgs e)=>LogsPanel.Visibility=LogsPanel.Visibility==Visibility.Visible?Visibility.Collapsed:Visibility.Visible;
    async void ToggleAnnotationSettings(object sender,RoutedEventArgs e)=>await vm.RunAction("settings");
    void ProjectMenu(object sender,RoutedEventArgs e){if(sender is System.Windows.Controls.Button button&&button.ContextMenu is { } menu){menu.PlacementTarget=button;menu.IsOpen=true;}}
    async void FileSelection(object sender,SelectionChangedEventArgs e)
    {
        if(syncing||sender is not ListBox list||list.SelectedItem is not ImageEntry image)return;
        if(image.Name!=vm.CurrentName)await vm.Safe(()=>vm.OpenImage(image.Name));
        if(vm.CurrentName!=image.Name){syncing=true;list.SelectedItem=vm.Images.FirstOrDefault(x=>x.Name==vm.CurrentName);syncing=false;}
    }
    async void AnnotateDoubleClick(object sender,MouseButtonEventArgs e)=>await vm.RunAction("annotation");
    void ClassSelection(object sender,SelectionChangedEventArgs e){if(Canvas is not null)Canvas.ClassId=Math.Max(0,vm.SelectedClass);}
    void ObjectSelection(object sender,SelectionChangedEventArgs e){if(!syncing&&ObjectList.SelectedItem is ObjectEntry item)Canvas.Select(item.Index);}
    async void TrashImages(object sender,RoutedEventArgs e)=>await vm.Safe(()=>vm.Trash(LibraryFiles.SelectedItems.Cast<ImageEntry>().Select(i=>i.Name).ToArray()));
    async void TransferImages(object sender,RoutedEventArgs e)=>await vm.Safe(()=>vm.Transfer(LibraryFiles.SelectedItems.Cast<ImageEntry>().Select(i=>i.Name).ToArray(),(sender as FrameworkElement)?.Tag?.ToString()=="move"));
    void ExperimentSelection(object sender,SelectionChangedEventArgs e)=>vm.ShowExperiment(ExperimentList.SelectedIndex);
    void CompareExperiments(object sender,RoutedEventArgs e)=>vm.CompareExperiments(ExperimentList.SelectedItems.Cast<object>().Select(x=>ExperimentList.Items.IndexOf(x)).ToArray());
    async void RecentProject(object sender,MouseButtonEventArgs e){if((sender as ListBox)?.SelectedItem is StudioViewModel.RecentEntry entry)await vm.Safe(()=>vm.OpenProject(entry.Path));}
    void WindowDragOver(object sender,DragEventArgs e){e.Effects=e.Data.GetDataPresent(DataFormats.FileDrop)?DragDropEffects.Copy:DragDropEffects.None;e.Handled=true;}
    async void WindowDrop(object sender,DragEventArgs e)
    {
        if(e.Data.GetData(DataFormats.FileDrop) is string[] paths)await vm.Safe(()=>vm.ImportChainedFiles(paths,false));
    }
    async void OnClosing(object? sender,CancelEventArgs e)
    {
        Canvas.StopNavigation();if(closing)return;e.Cancel=true;
        if(vm.Busy)
        {
            if(Services.UserDialogs.Confirm("任务正在运行。请求停止并等待输出保存？"))await vm.RunAction("stop");return;
        }
        if(!await vm.Save())return;closing=true;vm.Dispose();_=Dispatcher.BeginInvoke(Close);
    }
}
