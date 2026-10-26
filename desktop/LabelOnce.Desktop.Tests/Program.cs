using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Diagnostics;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using LabelOnce.Core;
using LabelOnce.Desktop;
using LabelOnce.Desktop.Controls;
using LabelOnce.Desktop.ViewModels;

internal static class Program
{
    [STAThread] static void Main(string[] args)
    {
        Console.OutputEncoding=System.Text.Encoding.UTF8;
        if(args[0]=="--release-smoke"){ReleaseSmoke(args);return;}
        var app=new Application();
        app.Resources.MergedDictionaries.Add(new Wpf.Ui.Markup.ThemesDictionary { Theme=Wpf.Ui.Appearance.ApplicationTheme.Dark });
        app.Resources.MergedDictionaries.Add(new Wpf.Ui.Markup.ControlsDictionary());
        app.Resources.MergedDictionaries.Add(new ResourceDictionary{Source=new Uri("pack://application:,,,/LabelOnce;component/Styles.xaml")});
        var window=new MainWindow(false);app.MainWindow=window;
        window.Loaded+=async(s,e)=>
        {
            var results=new List<object>();string root=Path.GetFullPath(args[0]);Directory.CreateDirectory(root);
            try
            {
                var vm=(StudioViewModel)window.DataContext;
                for(int i=0;vm.Status.StartsWith("正在连接")&&i<100;i++)await Task.Delay(100);
                await vm.OpenProject(args[1]);
                var canvas=(AnnotationCanvas)window.FindName("Canvas");
                if(args.Contains("--review-navigation"))
                {
                    await vm.RunAction("annotation");
                    vm.SelectedBatch="全部批次";vm.Search="";vm.Filter="全部素材";
                    var names=vm.Images.Select(i=>i.Name).ToArray();
                    if(names.Length<3)throw new Exception("需要至少三张测试图片");
                    await vm.OpenImage(names[0]);vm.Search=names[0];
                    if(vm.Images.Count!=1)throw new Exception("测试筛选未缩为单张");
                    await vm.Navigate(1);
                    if(vm.CurrentName!=names[1]||!vm.CurrentPosition.StartsWith($"2 / {names.Length}"))throw new Exception("筛选阻断批次导航");
                    await vm.Navigate(-1);if(vm.CurrentName!=names[0])throw new Exception("上一张失效");
                    vm.Filter="存在问题";await vm.Navigate(1);
                    if(vm.CurrentName!=names[1])throw new Exception("问题筛选阻断导航");
                    var key=new KeyEventArgs(Keyboard.PrimaryDevice,PresentationSource.FromVisual(window),0,System.Windows.Input.Key.D){RoutedEvent=Keyboard.PreviewKeyDownEvent};
                    typeof(MainWindow).GetMethod("WindowKeyDown",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,[window,key]);
                    for(int i=0;vm.CurrentName!=names[2]&&i<50;i++)await Task.Delay(100);
                    if(!key.Handled||vm.CurrentName!=names[2])throw new Exception("工作台 D 导航失效");
                    vm.Search="";vm.Filter="全部素材";
                    File.WriteAllText(Path.Combine(root,"review-navigation.json"),JsonSerializer.Serialize(new{pass=true,count=names.Length,scope="search/status filtered navigation, previous/next, window routed D"}));
                    Console.WriteLine("PASS: filtered batch review and window navigation");vm.Dispose();app.Shutdown(0);return;
                }
                if(args.Contains("--polygon-contract"))
                {
                    await vm.OpenImage("fixture_00.jpg");canvas.SetBoxes([]);canvas.SetMode("polygon");
                    var points=(List<double[]>)typeof(AnnotationCanvas).GetField("newPolygon",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(canvas)!;
                    points.AddRange(new[]{new[]{.2,.2},new[]{.7,.2},new[]{.6,.7},new[]{.2,.6}});
                    bool categoryShown=false;var timer=new System.Windows.Threading.DispatcherTimer{Interval=TimeSpan.FromMilliseconds(100)};
                    timer.Tick+=(_,_)=>{var dialog=Application.Current.Windows.Cast<Window>().FirstOrDefault(w=>w.Title=="确认类别");if(dialog!=null){categoryShown=true;Descendants<System.Windows.Controls.Button>(dialog).First(b=>b.IsDefault).RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent));timer.Stop();}};
                    timer.Start();var escArgs=new KeyEventArgs(Keyboard.PrimaryDevice,PresentationSource.FromVisual(canvas),0,System.Windows.Input.Key.Escape){RoutedEvent=Keyboard.KeyDownEvent};
                    typeof(AnnotationCanvas).GetMethod("OnKeyDown",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(canvas,[escArgs]);
                    for(int i=0;canvas.Boxes.Count==0&&i<50;i++)await Task.Delay(100);timer.Stop();
                    if(!categoryShown||canvas.Mode!="select"||canvas.Boxes.Count!=1||canvas.Boxes[0].Polygons?[0].Count!=4)throw new Exception("Esc/类别确认/轮廓提交失败");
                    string polygon=JsonSerializer.Serialize(canvas.Boxes[0].Polygons);
                    await vm.OpenImage("fixture_02.jpg");await vm.OpenImage("fixture_00.jpg");
                    if(JsonSerializer.Serialize(canvas.Boxes[0].Polygons)!=polygon)throw new Exception("多边形自动保存重开不一致");
                    File.WriteAllText(Path.Combine(root,"polygon-contract.json"),JsonSerializer.Serialize(new{pass=true,categoryShown,polygon,scope="WPF routed Escape and dialog, service autosave/reload; no native mouse coverage"}));
                    Console.WriteLine("PASS: polygon Escape/category/autosave/reload contract");vm.Dispose();app.Shutdown(0);return;
                }
                await vm.RunAction("annotation");
                await Foreground(window);
                foreach(var size in new[]{(1366d,768d),(1920d,1080d),(2560d,1440d)})
                foreach(var name in new[]{"fixture_00.jpg","fixture_01.jpg","fixture_02.jpg","fixture_03.jpg","fixture_04.jpg"})
                {
                    window.WindowState=WindowState.Normal;window.Width=size.Item1;window.Height=size.Item2;window.Left=0;window.Top=0;
                    await vm.OpenImage(name);await Settle(window);
                    var v=canvas.View;
                    if(v.DisplayWidth*v.Scale>canvas.ActualWidth-16+.001||v.DisplayHeight*v.Scale>canvas.ActualHeight-16+.001)throw new Exception("图片未完整适配");
                    results.Add(new{test="fit",size=new[]{size.Item1,size.Item2},name,canvas=new[]{canvas.ActualWidth,canvas.ActualHeight},scale=v.Scale,orientation=v.Orientation,pass=true});
                    if(size.Item1==1366||name=="fixture_01.jpg")Capture(window,Path.Combine(root,$"window-{size.Item1}x{size.Item2}-{name}.png"));
                }
                window.WindowState=WindowState.Normal;window.Width=900;window.Height=700;await Settle(window);
                var sidebar=(Border)window.FindName("Sidebar");if(sidebar.Visibility!=Visibility.Collapsed)throw new Exception($"窄窗口未折叠侧栏：ActualWidth={window.ActualWidth}, State={window.WindowState}");
                Capture(window,Path.Combine(root,"window-narrow.png"));results.Add(new{test="sidebar-auto-collapse",pass=true});
                window.Width=1366;window.Height=768;await vm.OpenImage("fixture_00.jpg");
                canvas.View.Zoom(new(250,200),2);var old=canvas.View.Scale;await vm.OpenImage("fixture_01.jpg");if(!canvas.View.IsFit||canvas.View.Scale==old)throw new Exception("切图未恢复适配");
                var original=canvas.Boxes.Select(b=>b.Copy()).ToList();canvas.SetBoxes([new Annotation{ClassId=0,X1=.1,Y1=.1,X2=.8,Y2=.7}]);canvas.Undo(-1);if(canvas.Boxes[0].X1!=original[0].X1)throw new Exception("撤销失效");canvas.Undo(1);if(canvas.Boxes[0].X1!=.1)throw new Exception("重做失效");
                canvas.SetBoxes(original);if(!await vm.Save())throw new Exception("保存失败");results.Add(new{test="history-and-save",pass=true});
                var labels=Path.Combine(args[1],"Main_labels","fixture_01.txt");
                canvas.SetBoxes([new Annotation{ClassId=0,X1=.2,Y1=.1,X2=.8,Y2=.7}]);
                using(var locked=new FileStream(labels,FileMode.Open,FileAccess.ReadWrite,FileShare.None))
                {await vm.OpenImage("fixture_02.jpg");if(vm.CurrentName!="fixture_01.jpg"||!vm.Dirty)throw new Exception("保存失败后丢失编辑或切图");}
                canvas.SetBoxes(original);if(!await vm.Save())throw new Exception("保存重试失败");results.Add(new{test="failed-save-retains-edits-and-retry",pass=true});
                // Exercise native routed mouse/keyboard input on the actual canvas.
                await Foreground(window);canvas.Focus();
                canvas.SetMode("draw");int count=canvas.Boxes.Count;
                var dialogTimer=new System.Windows.Threading.DispatcherTimer{Interval=TimeSpan.FromMilliseconds(100)};
                dialogTimer.Tick+=(_,_)=>{var dialog=Application.Current.Windows.Cast<Window>().FirstOrDefault(w=>w.Title=="确认类别");if(dialog is not null){if(canvas.Boxes.Count!=count)throw new Exception("类别确认前已提交矩形");Descendants<System.Windows.Controls.Button>(dialog).First(b=>b.IsDefault).RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent));dialogTimer.Stop();}};
                dialogTimer.Start();
                var anchor=canvas.PointToScreen(new Point(canvas.View.ToScreen(new(canvas.View.Width*.1,canvas.View.Height*.1)).X,canvas.View.ToScreen(new(canvas.View.Width*.1,canvas.View.Height*.1)).Y));
                var endpoint=canvas.PointToScreen(new Point(canvas.View.ToScreen(new(canvas.View.Width*.4,canvas.View.Height*.4)).X,canvas.View.ToScreen(new(canvas.View.Width*.4,canvas.View.Height*.4)).Y));
                MoveAndButton(anchor,2);await Task.Delay(50);MoveAndButton(anchor,4);await Task.Delay(80);
                if(canvas.Boxes.Count!=count||canvas.HasCandidate)throw new Exception("第一下不应创建完整候选");
                MoveAndButton(endpoint,0);await Task.Delay(100);MoveAndButton(endpoint,2);await Task.Delay(50);MoveAndButton(endpoint,4);
                for(int wait=0;canvas.Boxes.Count==count&&wait<50;wait++)await Task.Delay(100);
                dialogTimer.Stop();
                if(canvas.Boxes.Count!=count+1)throw new Exception($"实际鼠标绘框失败：只读={canvas.ReadOnly}, 类别={canvas.ClassId}/{canvas.Classes.Length}, 模式={canvas.Mode}, 前台={GetForegroundWindow()}, 自身={new WindowInteropHelper(window).Handle}, 鼠标={Mouse.GetPosition(canvas)}, 画布={canvas.ActualWidth}x{canvas.ActualHeight}");
                if(canvas.Mode!="select")throw new Exception("绘框确认后未回到选择工具");
                var drawn=canvas.Boxes[^1].Copy();
                if(Math.Abs(drawn.X1-.1)>.02||Math.Abs(drawn.Y1-.1)>.02||Math.Abs(drawn.X2-.4)>.02||Math.Abs(drawn.Y2-.4)>.02)throw new Exception($"原生输入坐标异常：{JsonSerializer.Serialize(drawn)}");
                canvas.SetMode("select");
                await Drag(canvas,canvas.View.ToScreen(new(canvas.View.Width*.25,canvas.View.Height*.25)),canvas.View.ToScreen(new(canvas.View.Width*.35,canvas.View.Height*.3)));
                if(canvas.Boxes[^1].X1<=drawn.X1+.05)throw new Exception($"实际鼠标移动框失败：before={JsonSerializer.Serialize(drawn)}, after={JsonSerializer.Serialize(canvas.Boxes[^1])}, foreground={GetForegroundWindow()}, own={new WindowInteropHelper(window).Handle}");
                var moved=canvas.Boxes[^1].Copy();
                await Drag(canvas,canvas.View.ToScreen(new(moved.X2*canvas.View.Width,moved.Y2*canvas.View.Height)),canvas.View.ToScreen(new((moved.X2+.1)*canvas.View.Width,(moved.Y2+.1)*canvas.View.Height)));
                if(canvas.Boxes[^1].X2<=moved.X2+.05)throw new Exception("实际鼠标缩放框失败");
                await Key(0x43,true);await Key(0x56,true);if(canvas.Boxes.Count!=count+2)throw new Exception("Ctrl C/V 失败");
                await Key(0x2E);if(canvas.Boxes.Count!=count+1)throw new Exception("Delete 失败");
                await Key(0x5A,true);if(canvas.Boxes.Count!=count+2)throw new Exception("Ctrl Z 失败");
                await Key(0x59,true);if(canvas.Boxes.Count!=count+1)throw new Exception("Ctrl Y 失败");
                // Each visible handle has a different hit-test index and resize branch.
                foreach(var handle in new[]{(.3,.3,-.05,-.05),(.45,.3,0,-.05),(.6,.3,.05,-.05),(.6,.45,.05,0),(.6,.6,.05,.05),(.45,.6,0,.05),(.3,.6,-.05,.05),(.3,.45,-.05,0)})
                {
                    canvas.SetBoxes([new Annotation{ClassId=0,X1=.3,Y1=.3,X2=.6,Y2=.6}]);canvas.Select(0);
                    await Drag(canvas,canvas.View.ToScreen(new(handle.Item1*canvas.View.Width,handle.Item2*canvas.View.Height)),canvas.View.ToScreen(new((handle.Item1+handle.Item3)*canvas.View.Width,(handle.Item2+handle.Item4)*canvas.View.Height)));
                    double ex1=.3+Math.Min(0,handle.Item3),ey1=.3+Math.Min(0,handle.Item4),ex2=.6+Math.Max(0,handle.Item3),ey2=.6+Math.Max(0,handle.Item4);
                    for(int settle=0;settle<12;settle++)
                    {
                        var r0=canvas.Boxes[0];
                        if(Math.Abs(r0.X1-ex1)<=.01&&Math.Abs(r0.Y1-ey1)<=.01&&Math.Abs(r0.X2-ex2)<=.01&&Math.Abs(r0.Y2-ey2)<=.01)break;
                        await Task.Delay(50);
                    }
                    var resized=canvas.Boxes[0];
                    if(Math.Abs(resized.X1-ex1)>.01||Math.Abs(resized.Y1-ey1)>.01||Math.Abs(resized.X2-ex2)>.01||Math.Abs(resized.Y2-ey2)>.01)throw new Exception($"八方向手柄失效：{handle}, {JsonSerializer.Serialize(resized)}, 只读={canvas.ReadOnly}, 模式={canvas.Mode}, 前台={GetForegroundWindow()}, 自身={new WindowInteropHelper(window).Handle}, 鼠标={Mouse.GetPosition(canvas)}, 画布={canvas.ActualWidth}x{canvas.ActualHeight}");
                }
                canvas.SetBoxes(original);await vm.Save();results.Add(new{test="native-draw-move-eight-resize-handles-copy-paste-delete-history",pass=true});
                // Native vertex drag and history use original image coordinates.
                canvas.SetBoxes([new Annotation{ClassId=0,X1=.2,Y1=.2,X2=.7,Y2=.7,Polygons=[[[.2,.2],[.7,.2],[.7,.7],[.2,.7]]],Roi=[.1,.1,.8,.8]}]);canvas.Select(0);canvas.SetMode("select");
                await Drag(canvas,canvas.View.ToScreen(new(canvas.View.Width*.2,canvas.View.Height*.2)),canvas.View.ToScreen(new(canvas.View.Width*.3,canvas.View.Height*.3)));
                if(Math.Abs(canvas.Boxes[0].Polygons![0][0][0]-.3)>.02)throw new Exception("顶点拖动失败");
                canvas.Delete();if(canvas.Boxes[0].Polygons![0].Count!=3)throw new Exception("顶点删除失败");
                canvas.Undo(-1);if(canvas.Boxes[0].Polygons![0].Count!=4)throw new Exception("顶点撤销失败");
                canvas.Undo(-1);if(Math.Abs(canvas.Boxes[0].Polygons![0][0][0]-.2)>.001)throw new Exception("顶点拖动撤销失败");
                canvas.SetBoxes(original);await vm.Save();results.Add(new{test="native-polygon-vertex-drag-delete-undo",pass=true});
                foreach(bool polygon in new[]{false,true})
                {
                    canvas.SetBoxes([new Annotation{ClassId=0,ObjectId=Guid.NewGuid().ToString(),X1=.2,Y1=.2,X2=.7,Y2=.7,Polygons=polygon?[[[.2,.2],[.7,.2],[.7,.7],[.2,.7]]]:null}]);
                    canvas.SetMode("select");var screen=canvas.View.ToScreen(new(canvas.View.Width*.4,canvas.View.Height*.4));var location=canvas.PointToScreen(new Point(screen.X,screen.Y));
                    MoveAndButton(location,8);await Task.Delay(80);MoveAndButton(location,16);await Task.Delay(150);
                    if(canvas.ContextMenu is not {IsOpen:true} menu)throw new Exception("右键对象未打开菜单");
                    ((MenuItem)menu.Items[0]).RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));menu.IsOpen=false;
                    if(canvas.Boxes.Count!=0)throw new Exception("右键应删除整个对象");canvas.Undo(-1);
                    if(canvas.Boxes.Count!=1)throw new Exception("右键删除不可撤销");
                }
                canvas.SetBoxes(original);await vm.Save();results.Add(new{test="context-delete-box-polygon-and-undo",pass=true});
                canvas.SetBoxes([]);count=0;canvas.SetMode("polygon");dialogTimer.Start();
                foreach(var xy in new[]{(.2,.2),(.6,.2),(.6,.6),(.2,.6)}){var pt=canvas.View.ToScreen(new(canvas.View.Width*xy.Item1,canvas.View.Height*xy.Item2));var scr=canvas.PointToScreen(new Point(pt.X,pt.Y));MoveAndButton(scr,2);await Task.Delay(50);MoveAndButton(scr,4);await Task.Delay(550);}
                await Key(0x1B);for(int i=0;canvas.Boxes.Count==0&&i<40;i++)await Task.Delay(100);dialogTimer.Stop();
                if(canvas.Boxes.Count!=1||canvas.Boxes[0].Polygons?[0].Count!=4)throw new Exception("Esc 闭合多边形失败");
                var polygonJson=JsonSerializer.Serialize(canvas.Boxes[0].Polygons);string polygonImage=vm.CurrentName;
                await vm.OpenImage("fixture_02.jpg");await vm.OpenImage(polygonImage);
                if(JsonSerializer.Serialize(canvas.Boxes[0].Polygons)!=polygonJson)throw new Exception("自动保存重开丢失多边形轮廓");
                results.Add(new{test="polygon-escape-category-autosave-reload",pass=true});
                int nav=0,confirms=0;canvas.Navigate+=_=>nav++;canvas.Confirm+=()=>confirms++;
                // A/D 大小写路由：窗口级 PreviewKeyDown 把 A/D 转给素材列表（WindowKeyDown），画布级连发计时器不再是 D 的入口。
                canvas.Focus();await Foreground(window);
                var transitioningField=typeof(StudioViewModel).GetField("transitioning",BindingFlags.NonPublic|BindingFlags.Instance)!;
                for(int i=0;(vm.Saving||(bool)transitioningField.GetValue(vm)!)&&i<100;i++)await Task.Delay(100);
                var reviewList=()=>((IEnumerable<ImageEntry>)typeof(StudioViewModel).GetProperty("ReviewImages",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(vm)!).ToList();
                var startList=reviewList();int navStart=startList.FindIndex(x=>x.Name==vm.CurrentName);
                for(int press=0;press<4;press++){keybd_event(0x44,0,0,UIntPtr.Zero);await Task.Delay(100);keybd_event(0x44,0,2,UIntPtr.Zero);for(int i=0;(vm.Saving||(bool)transitioningField.GetValue(vm)!)&&i<100;i++)await Task.Delay(100);}
                for(int i=0;(vm.Saving||(bool)transitioningField.GetValue(vm)!)&&i<100;i++)await Task.Delay(100);
                if(vm.Saving||(bool)transitioningField.GetValue(vm)!)throw new Exception("导航操作未在超时前结束");
                var endList=reviewList();int navEnd=endList.FindIndex(x=>x.Name==vm.CurrentName);
                if(navEnd!=(navStart+4)%endList.Count)throw new Exception($"A/D 长按多步推进失败：起点={navStart}, 终点={navEnd}, 期望={(navStart+4)%endList.Count}, 确认={confirms}, 焦点={Keyboard.FocusedElement}, 状态={vm.Status}");
                string navHold=vm.CurrentName;await Task.Delay(400);
                if(vm.CurrentName!=navHold||confirms!=0)throw new Exception($"松开 D 后自行推进或误确认：{navHold}→{vm.CurrentName}, 确认={confirms}");
                string confirmedImage=vm.CurrentName;
                await Foreground(window);canvas.Focus();keybd_event(0x46,0,0,UIntPtr.Zero);
                for(int repeat=0;repeat<4;repeat++){await Task.Delay(200);keybd_event(0x46,0,0,UIntPtr.Zero);}
                keybd_event(0x46,0,2,UIntPtr.Zero);await Task.Delay(200);
                if(confirms!=1)throw new Exception($"F 单次确认失败：次数={confirms}, Focus={Keyboard.FocusedElement}, ReadOnly={canvas.ReadOnly}, Status={vm.Status}");
                for(int i=0;(vm.Saving||(bool)transitioningField.GetValue(vm)!)&&i<100;i++)await Task.Delay(100);
                if(vm.Saving||(bool)transitioningField.GetValue(vm)!)throw new Exception("确认跳转未在超时前结束");
                if(vm.CurrentName==confirmedImage)throw new Exception($"完成 F 应确认并跳到下一张待完成图片：before={confirmedImage}, after={vm.CurrentName}, busy={vm.Busy}, saving={vm.Saving}, transitioning={(bool)transitioningField.GetValue(vm)!}, 状态={vm.Status}");
                results.Add(new{test="native-navigation-release-and-single-confirm-advances",pass=true});
                foreach(var pair in new[]{("train-page","training"),("model-page","models"),("settings","settings"),("library","library")})
                {await vm.RunAction(pair.Item1);await Settle(window);Capture(window,Path.Combine(root,$"page-{pair.Item2}.png"));}
                await vm.RunAction("settings");await Settle(window);
                var input=Descendants<System.Windows.Controls.TextBox>(window).First(x=>x.IsVisible&&!x.IsReadOnly);
                input.Focus();int beforeInput=nav+confirms;await Key(0x44);await Key(0x46);
                if(nav+confirms!=beforeInput)throw new Exception("输入框触发画布快捷键");results.Add(new{test="input-shortcut-isolation",pass=true});
                string fixtures=args.Length>2?Path.GetFullPath(args[2]):Path.Combine(Path.GetDirectoryName(Path.GetFullPath(args[1]))!,"fixtures");
                await vm.OpenVideo(Path.Combine(fixtures,"portrait.mp4"));await Settle(window);
                canvas.SetBoxes([new Annotation{ClassId=0,TargetId=0,X1=.2,Y1=.2,X2=.7,Y2=.8}]);canvas.NextTargetId=3;
                canvas.View.Zoom(new(200,200),1.7);double videoScale=canvas.View.Scale;var offset=canvas.View.Offset;
                await vm.VideoFrame(1);if(canvas.View.Scale!=videoScale||canvas.View.Offset!=offset||canvas.NextTargetId!=3)throw new Exception("视频切帧未保留视角或 ID");
                await vm.VideoFrame(0);if(canvas.Boxes.Count!=1||canvas.Boxes[0].TargetId!=0)throw new Exception("逐帧草稿丢失");
                await vm.OpenVideo(Path.Combine(fixtures,"landscape.mp4"));if(!canvas.View.IsFit||canvas.NextTargetId!=0)throw new Exception("新视频未重置视角或 ID");
                await Settle(window);Capture(window,Path.Combine(root,"window-video.png"));results.Add(new{test="video-viewport-drafts-and-lifetime-ids",pass=true});
                await vm.OpenImage("fixture_01.jpg");
                ((FrameworkElement)window.FindName("VideoBar")).Visibility=Visibility.Collapsed;
                foreach(var pixels in new[]{(1366,768),(1920,1080),(2560,1440)})
                {
                    var dpi=VisualTreeHelper.GetDpi(window);window.Width=pixels.Item1/dpi.DpiScaleX;window.Height=pixels.Item2/dpi.DpiScaleY;
                    if(Math.Abs(window.Width*dpi.DpiScaleX-pixels.Item1)>2||Math.Abs(window.Height*dpi.DpiScaleY-pixels.Item2)>2)throw new Exception("物理窗口尺寸受最小尺寸限制");
                    await Settle(window);Capture(window,Path.Combine(root,$"physical-{pixels.Item1}x{pixels.Item2}.png"));
                    results.Add(new{test="physical-window-size",pixels=new[]{pixels.Item1,pixels.Item2},dpi=dpi.DpiScaleX,actualDip=new[]{window.ActualWidth,window.ActualHeight},pass=true});
                }
                vm.Acrylic=false;await vm.RunAction("settings-save");await vm.RunAction("annotation");await Settle(window);Capture(window,Path.Combine(root,"window-opaque-fallback.png"));
                vm.Acrylic=true;await vm.RunAction("settings-save");
                window.WindowState=WindowState.Maximized;await Task.Delay(200);Capture(window,Path.Combine(root,"window-maximized.png"));results.Add(new{test="maximize-and-opaque-fallback",pass=true});
                window.WindowState=WindowState.Normal;window.Width=1280;window.Height=720;window.Left=0;window.Top=0;
                vm.EpochMetrics=[new(1,2.4,.15),new(2,1.8,.3),new(3,1.2,.55)];await vm.RunAction("train-page");await Foreground(window);Capture(window,Path.Combine(root,"training-curve-render-fixture.png"));
                // Synthetic epoch data validates only drawing; GPU training has its own report.
                results.Add(new{test="live-curve-render-fixture",pass=true});
                await vm.RunAction("annotation");await vm.OpenImage("fixture_01.jpg");
                canvas.SetBoxes([new Annotation{ClassId=0,X1=.15,Y1=.2,X2=.6,Y2=.8}]);
                var bridgeField=typeof(StudioViewModel).GetField("bridge",BindingFlags.NonPublic|BindingFlags.Instance)!;
                var bridge=bridgeField.GetValue(vm)!;
                var backend=(Process)bridge.GetType().GetField("process",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(bridge)!;
                vm.Busy=true;backend.Kill(true);
                for(int i=0;vm.Busy&&i<100;i++)await Task.Delay(100);
                if(vm.Busy||!vm.Dirty||canvas.Boxes[0].X1!=.15)throw new Exception("后端异常退出未保留编辑或释放任务状态");
                await vm.RunAction("restart");if(!await vm.Save())throw new Exception("后端重启后无法重试保存");
                canvas.SetBoxes(original);await vm.Save();results.Add(new{test="backend-crash-unlocks-preserves-edits-and-restarts",pass=true});
                File.WriteAllText(Path.Combine(root,"desktop-report.json"),JsonSerializer.Serialize(results,new JsonSerializerOptions{WriteIndented=true}));
                Console.WriteLine($"PASS: {results.Count} WPF integration checks");
                vm.Dispose();app.Shutdown(0);
            }
            catch(Exception exc){var probeVm=window?.DataContext as StudioViewModel;File.WriteAllText(Path.Combine(root,"desktop-error.txt"),exc.ToString()+Environment.NewLine+"STATUS: "+(probeVm?.Status??"")+"|PROJECT: "+(probeVm?.Project??"")+"|CURRENT: "+(probeVm?.CurrentName??"")+Environment.NewLine+"LOG:"+Environment.NewLine+(probeVm?.Log??Console.Out.ToString()??""),Encoding.UTF8);Console.Error.WriteLine(exc);app.Shutdown(1);}
        };
        window.Show();app.Run();
    }
    static async Task Settle(Window window)
    {
        window.UpdateLayout();
        await window.Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ApplicationIdle);
        await Task.Delay(500);
        DwmFlush();
    }
    static async Task Foreground(Window window)
    {
        window.Topmost=true;var hwnd=new WindowInteropHelper(window).Handle;
        ShowWindow(hwnd,9);window.Activate();
        uint thread=GetCurrentThreadId(),foreground=GetWindowThreadProcessId(GetForegroundWindow(),out _);
        bool attached=foreground!=thread&&AttachThreadInput(thread,foreground,true);
        try{BringWindowToTop(hwnd);SetForegroundWindow(hwnd);}finally{if(attached)AttachThreadInput(thread,foreground,false);}
        await Settle(window);
        if(GetForegroundWindow()!=hwnd)
        {
            // Clicking this test window's title requests focus through normal input.
            var title=window.PointToScreen(new Point(250,20));SetCursorPos((int)title.X,(int)title.Y);mouse_event(2,0,0,0,UIntPtr.Zero);mouse_event(4,0,0,0,UIntPtr.Zero);await Task.Delay(250);
        }
        if(GetForegroundWindow()!=hwnd)throw new Exception("测试窗口无法获取前台，原生输入测试未执行");
    }
    static IEnumerable<T> Descendants<T>(DependencyObject parent) where T:DependencyObject
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++)
        {var child=VisualTreeHelper.GetChild(parent,i);if(child is T found)yield return found;foreach(var item in Descendants<T>(child))yield return item;}
    }
    static async Task Drag(FrameworkElement target,PointD a,PointD b)
    {
        var p=target.PointToScreen(new Point(a.X,a.Y));var q=target.PointToScreen(new Point(b.X,b.Y));
        MoveAndButton(p,2);await Task.Delay(100);MoveAndButton(q,4);await Task.Delay(100);
    }
    static void MoveAndButton(Point position,uint button)
    {
        int left=GetSystemMetrics(76),top=GetSystemMetrics(77),width=GetSystemMetrics(78),height=GetSystemMetrics(79);
        var input=new[]{new INPUT{type=0,mouse=new MOUSEINPUT{dx=(int)Math.Round((position.X-left)*65535/(width-1)),dy=(int)Math.Round((position.Y-top)*65535/(height-1)),flags=0x8000|0x4000|1}},new INPUT{type=0,mouse=new MOUSEINPUT{flags=button}}};
        if(SendInput((uint)input.Length,input,Marshal.SizeOf<INPUT>())!=input.Length)throw new Exception("SendInput failed");
    }
    static async Task Key(byte key,bool ctrl=false)
    {
        if(ctrl)keybd_event(0x11,0,0,UIntPtr.Zero);keybd_event(key,0,0,UIntPtr.Zero);await Task.Delay(60);keybd_event(key,0,2,UIntPtr.Zero);if(ctrl)keybd_event(0x11,0,2,UIntPtr.Zero);await Task.Delay(100);
    }
    static void Capture(Window window,string path)
    {
        CaptureHandle(new WindowInteropHelper(window).Handle,path);
    }
    static void CaptureHandle(IntPtr hwnd,string path)
    {
        GetWindowRect(hwnd,out var r);int width=r.Right-r.Left,height=r.Bottom-r.Top;
        var screen=GetDC(IntPtr.Zero);var dc=CreateCompatibleDC(screen);var bitmap=CreateCompatibleBitmap(screen,width,height);var previous=SelectObject(dc,bitmap);
        try
        {
            PatBlt(dc,0,0,width,height,0x00000042);
            RedrawWindow(hwnd,IntPtr.Zero,IntPtr.Zero,0x1|0x4|0x80|0x100);DwmFlush();
            bool visible=GetForegroundWindow()==hwnd&&r.Left>=0&&r.Top>=0&&r.Right<=GetSystemMetrics(0)&&r.Bottom<=GetSystemMetrics(1);
            if(visible){if(!BitBlt(dc,0,0,width,height,screen,r.Left,r.Top,0x00CC0020))throw new Exception("BitBlt failed");}
            else if(!PrintWindow(hwnd,dc,2))throw new Exception("PrintWindow failed");
            var image=Imaging.CreateBitmapSourceFromHBitmap(bitmap,IntPtr.Zero,Int32Rect.Empty,BitmapSizeOptions.FromEmptyOptions());var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using var stream=File.Create(path);encoder.Save(stream);
        }
        finally{SelectObject(dc,previous);DeleteObject(bitmap);DeleteDC(dc);ReleaseDC(IntPtr.Zero,screen);}
    }
    static void ReleaseSmoke(string[] args)
    {
        SetThreadDpiAwarenessContext(new IntPtr(-4));
        var info=new ProcessStartInfo(Path.GetFullPath(args[1])){UseShellExecute=false,WorkingDirectory=Path.GetTempPath()};
        foreach(var key in info.Environment.Keys.ToArray())if(new[]{"CONDA","PYTHON","DOTNET","LABELONCE"}.Any(prefix=>key.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)))info.Environment.Remove(key);
        var system=Environment.GetEnvironmentVariable("SystemRoot")!;info.Environment["PATH"]=system+@"\System32;"+system;
        var output=Path.GetFullPath(args[3]);Directory.CreateDirectory(output);info.Environment["APPDATA"]=Path.Combine(output,"smoke-appdata");
        info.ArgumentList.Add(Path.GetFullPath(args[2]));
        using var process=Process.Start(info)!;
        try
        {
            for(int i=0;i<100;i++){process.Refresh();if(process.HasExited)throw new Exception("发布主程序提前退出");if(process.MainWindowHandle!=IntPtr.Zero)break;Thread.Sleep(100);}
            if(process.MainWindowHandle==IntPtr.Zero)throw new Exception("发布主程序未创建窗口");
            Thread.Sleep(8000);ShowWindow(process.MainWindowHandle,9);SetWindowPos(process.MainWindowHandle,new IntPtr(-1),0,0,1920,1080,0x0040);SetForegroundWindow(process.MainWindowHandle);DwmFlush();Thread.Sleep(1000);
            CaptureHandle(process.MainWindowHandle,Path.Combine(output,"release-main-window.png"));
            process.CloseMainWindow();if(!process.WaitForExit(15000))throw new Exception("发布主程序未正常关闭");
            if(process.ExitCode!=0)throw new Exception("发布主程序异常退出");
            File.WriteAllText(Path.Combine(output,"release-smoke.json"),JsonSerializer.Serialize(new{pass=true,exe=info.FileName,cwd=info.WorkingDirectory,path=info.Environment["PATH"],exitCode=process.ExitCode},new JsonSerializerOptions{WriteIndented=true}));
            Console.WriteLine("PASS: actual release executable, clean environment, native window and graceful exit");
        }
        finally{if(!process.HasExited)process.Kill(true);}
    }
    [StructLayout(LayoutKind.Sequential)]struct RECT{public int Left,Top,Right,Bottom;}
    [StructLayout(LayoutKind.Sequential)]struct MOUSEINPUT{public int dx,dy;public uint data,flags,time;public UIntPtr extra;}
    [StructLayout(LayoutKind.Sequential)]struct INPUT{public uint type;public MOUSEINPUT mouse;}
    [DllImport("user32.dll",SetLastError=true)]static extern uint SendInput(uint count,INPUT[] input,int size);
    [DllImport("user32.dll")]static extern bool GetWindowRect(IntPtr h,out RECT r);
    [DllImport("user32.dll")]static extern IntPtr GetDC(IntPtr h);
    [DllImport("user32.dll")]static extern int ReleaseDC(IntPtr h,IntPtr dc);
    [DllImport("user32.dll")]static extern bool PrintWindow(IntPtr h,IntPtr dc,uint flags);
    [DllImport("user32.dll")]static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")]static extern bool ShowWindow(IntPtr h,int command);
    [DllImport("user32.dll")]static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")]static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll")]static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int width,int height,uint flags);
    [DllImport("user32.dll")]static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")]static extern uint GetWindowThreadProcessId(IntPtr h,out uint process);
    [DllImport("kernel32.dll")]static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")]static extern bool AttachThreadInput(uint from,uint to,bool attach);
    [DllImport("user32.dll")]static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]static extern bool SetCursorPos(int x,int y);
    [DllImport("user32.dll")]static extern void mouse_event(uint flags,uint x,uint y,uint data,UIntPtr extra);
    [DllImport("user32.dll")]static extern void keybd_event(byte key,byte scan,uint flags,UIntPtr extra);
    [DllImport("user32.dll")]static extern bool RedrawWindow(IntPtr h,IntPtr rect,IntPtr region,uint flags);
    [DllImport("dwmapi.dll")]static extern int DwmFlush();
    [DllImport("gdi32.dll")]static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")]static extern IntPtr CreateCompatibleBitmap(IntPtr dc,int width,int height);
    [DllImport("gdi32.dll")]static extern IntPtr SelectObject(IntPtr dc,IntPtr value);
    [DllImport("gdi32.dll")]static extern bool PatBlt(IntPtr dc,int x,int y,int width,int height,uint operation);
    [DllImport("gdi32.dll")]static extern bool BitBlt(IntPtr dc,int x,int y,int width,int height,IntPtr source,int sourceX,int sourceY,uint operation);
    [DllImport("gdi32.dll")]static extern bool DeleteObject(IntPtr h);
    [DllImport("gdi32.dll")]static extern bool DeleteDC(IntPtr h);
}



