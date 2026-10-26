using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using LabelOnce.Core;
using LabelOnce.Desktop.Services;
using LabelOnce.Desktop.Controls;
using System.Windows.Media.Imaging;
namespace LabelOnce.Desktop.ViewModels;

public sealed record ImageEntry(string Name,string Path,string Status,string? Batch,string Source="")
{
    public string Description=>$"{Name} · {Status switch{"pending"=>"待完成","confirmed"=>"已完成","rejected"=>"已驳回",_=>"待标注"}}{Source}";
}
public sealed record ObjectEntry(int Index,int TargetId,string Name,string Origin);
public sealed record Document(string Path,string Source,int Width,int Height,int Orientation,List<Annotation> Boxes,bool Video);

public partial class StudioViewModel : ObservableObject, IDisposable
{
    public const int PageHome=0,PageLibrary=1,PageAnnotation=2,PageTraining=3,PageModel=4,PageSettings=5;
    readonly BridgeClient bridge=new();
    [ObservableProperty] string project="";
    [ObservableProperty] string projectTitle="Label Once";
    [ObservableProperty] string status="正在连接本地后端…";
    [ObservableProperty] string log="";
    [ObservableProperty] bool busy;
    [ObservableProperty] double progress;
    [ObservableProperty] string currentName="";
    [ObservableProperty] string activeRun="";
    [ObservableProperty] string selectedModel="";
    [ObservableProperty] string selectedSam="";
    [ObservableProperty] string selectedVersion="";
    [ObservableProperty] int selectedClass;
    [ObservableProperty] string filter="全部素材";
    [ObservableProperty] string device="0";
    [ObservableProperty] string modelDevice="0";
    [ObservableProperty] string source="";
    [ObservableProperty] string predictMode="image";
    [ObservableProperty] string exportFormat="onnx";
    [ObservableProperty] string precision="32";
    [ObservableProperty] double conf=.25;
    [ObservableProperty] double iou=.45;
    [ObservableProperty] int epochs=50;
    [ObservableProperty] int batch=16;
    [ObservableProperty] int imgsz=640;
    [ObservableProperty] double learningRate=.001;
    [ObservableProperty] int frameStep=10;
    [ObservableProperty] string videoState="idle";
    [ObservableProperty] int frame;
    [ObservableProperty] int totalFrames;
    [ObservableProperty] string videoName="";
    [ObservableProperty] int videoProgressFrame;
    [ObservableProperty] int videoProgressTotal;
    readonly List<(long Ticks,int Frame)> progressMarks=[];
    partial void OnVideoProgressFrameChanged(int value)=>MarkProgress(value);
    partial void OnVideoProgressTotalChanged(int value)=>OnPropertyChanged(nameof(VideoDetail));
    partial void OnVideoStateChanged(string value){OnPropertyChanged(nameof(VideoStateText));OnPropertyChanged(nameof(VideoStartText));OnPropertyChanged(nameof(VideoStartEnabled));}
    void MarkProgress(int value)
    {
        var now=Environment.TickCount64;
        if(progressMarks.Count>0&&value<=progressMarks[^1].Frame)return;
        progressMarks.Add((now,value));
        while(progressMarks.Count>12)progressMarks.RemoveAt(0);
        OnPropertyChanged(nameof(VideoDetail));
    }
    public string VideoDetail
    {
        get
        {
            if(VideoProgressTotal<=0)return "";
            var done=VideoProgressFrame;
            string eta="";
            if(Busy&&progressMarks.Count>=2&&done<VideoProgressTotal)
            {
                var dt=progressMarks[^1].Ticks-progressMarks[0].Ticks;
                var df=progressMarks[^1].Frame-progressMarks[0].Frame;
                if(dt>0&&df>0)eta=$" · 剩余约 {TimeSpan.FromMilliseconds((VideoProgressTotal-done)*dt/df):mm\\:ss}";
            }
            return $"帧 {done} / {VideoProgressTotal}{eta}";
        }
    }
    public string VideoStateText=>VideoState switch{"idle"=>"未开始","starting"=>"加载模型中","tracking"=>"追踪中","waiting"=>waitingAction=="commit"?"提交中…":"暂停中…","paused"=>"已暂停 · 可直接修正","completed"=>"已完成","failed"=>"失败","cancelled"=>"已停止",var v=>v};
    public string VideoStartText=>VideoState switch{"tracking"=>"暂停","paused"=>"提交纠偏","starting"=>"模型加载中…","waiting"=>waitingAction=="commit"?"提交中…":"暂停中…","idle"=>Busy?"任务运行中…":"启动追踪","completed"=>Busy?"任务运行中…":"启动追踪",_=>"启动追踪"};
    public bool VideoStartEnabled=>VideoState is "tracking" or "paused"||((VideoState is "idle" or "completed")&&!Busy);
    [ObservableProperty] string resultJson="";
    [ObservableProperty] string previewPath="";
    [ObservableProperty] string curvePath="";
    [ObservableProperty] BitmapSource? curveImage;
    [ObservableProperty] IReadOnlyList<TrainingEpoch> epochMetrics=[];
    [ObservableProperty] string brand="Label Once";
    [ObservableProperty] string logoPath="";
    [ObservableProperty] int samSize=1024;
    [ObservableProperty] bool acrylic=true;
    [ObservableProperty] bool dirty;
    [ObservableProperty] bool saving;
    [ObservableProperty] string viewStatus="适配";
    [ObservableProperty] string currentSourcePath="Label Once";
    public Func<Task<bool>> ResolveCandidate { get; set; }=()=>Task.FromResult(true);
    public double DisplayProgress=>Busy?Progress:ReviewTotal==0?0:(double)ReviewCompleted/ReviewTotal;
    IEnumerable<ImageEntry> ReviewImages=>allImages.Where(i=>SelectedBatch=="全部批次"?(Filter!="当前批次"||batchId is null||batchId.Length==0||i.Batch==batchId):i.Batch==SelectedBatch);
    public int ReviewTotal=>ReviewImages.Count(i=>i.Status!="rejected");
    public int ReviewCompleted=>ReviewImages.Count(i=>i.Status=="confirmed"&&!(i.Name==CurrentName&&Dirty));
    public string ProgressText=>Busy?$"{Status} · {Progress:P0}":SamWorking?"SAM 正在更新轮廓…":$"批次复核 · {ReviewCompleted} / {ReviewTotal}";
    public bool ProgressIndeterminate=>SamWorking&&!Busy;
    void NotifyProgress(){OnPropertyChanged(nameof(DisplayProgress));OnPropertyChanged(nameof(ProgressText));OnPropertyChanged(nameof(ProgressIndeterminate));}
    partial void OnBusyChanged(bool value){NotifyProgress();OnPropertyChanged(nameof(VideoDetail));OnPropertyChanged(nameof(VideoStartText));OnPropertyChanged(nameof(VideoStartEnabled));}
    partial void OnProgressChanged(double value)=>NotifyProgress();
    partial void OnStatusChanged(string value)=>NotifyProgress();
    partial void OnSamWorkingChanged(bool value)=>NotifyProgress();
    [ObservableProperty] string statsText="打开项目开始工作";
    [ObservableProperty] string gateStatusText="尚未运行门禁检查";
    [ObservableProperty] int page;
    [ObservableProperty] bool hasProject;
    [ObservableProperty] bool showHomeAtStartup=true;
    public ObservableCollection<ImageEntry> Images { get; }=[];
    public ObservableCollection<string> Classes { get; }=[];
    public ObservableCollection<ObjectEntry> Objects { get; }=[];
    public ObservableCollection<string> Models { get; }=[];
    public ObservableCollection<string> SamModels { get; }=[];
    public ObservableCollection<string> Versions { get; }=[];
    public sealed record RecentEntry(string Name,string Path);
    public ObservableCollection<RecentEntry> RecentProjects { get; }=[];
    public ObservableCollection<Dictionary<string,object>> Detections { get; }=[];
    public ObservableCollection<Dictionary<string,object>> Experiments { get; }=[];
    public string[] Filters { get; }=["全部素材","待完成","已完成","已驳回","当前批次","存在问题"];
    public ObservableCollection<string> Batches { get; }=[];
    [ObservableProperty] string selectedBatch="全部批次";
    readonly HashSet<string> problemImages=[];
    string? firstProblem;
    public string CurrentPosition
    {
        get
        {
            var review=ReviewImages.ToList();
            var index=review.FindIndex(i=>i.Name==CurrentName);
            return $"{index+1} / {review.Count} · {allImages.FirstOrDefault(i=>i.Name==CurrentName)?.Source}";
        }
    }
    static string SourceDescription(JsonElement m)=>Text(m,"video") is {Length:>0} video?$" · {Path.GetFileName(video)} · 原帧 {Number(m,"frame")} · {Text(m,"timestamp")} s":"";
    partial void OnSelectedBatchChanged(string value)=>FilterImages();
    partial void OnCurrentNameChanged(string value)=>OnPropertyChanged(nameof(CurrentPosition));
    public string[] Devices { get; }=["0","cpu","0,1"];
    public string[] PredictModes { get; }=["image","batch","video"];
    public string[] Formats { get; }=["onnx","openvino","engine","torchscript"];
    public string[] Precisions { get; }=["32","16","8"];
    public int[] FrameSteps { get; }=[5,10,15,20,30];
    public IAsyncRelayCommand<string> ActionCommand { get; }
    public Func<List<Annotation>> GetBoxes { get; set; }=()=>[];
    public Func<int> GetNextId { get; set; }=()=>0;
    public event Action<Document>? DocumentChanged;
    public event Action<string>? CanvasAction;
    public event Action? MaterialChanged;
    public event Action<int>? PageRequested;
    List<ImageEntry> allImages=[];
    List<Dictionary<string,object>> experiments=[];
    JsonElement settings;
    string? batchId,videoPath,videoSession,trackingSession,pauseToken;
    string taskKind="";
    string waitingAction="";
    long documentGeneration;
    int annotationRevision;
    JsonElement currentMetadata;
    bool taskSucceeded;
    string[] importedNames=[];
    [ObservableProperty] string search="";
    [ObservableProperty] string annotationMethod="手工标注";
    public System.Windows.Visibility YoloToolsVisibility=>AnnotationMethod=="YOLO 预标注"?System.Windows.Visibility.Visible:System.Windows.Visibility.Collapsed;
    public System.Windows.Visibility SamToolsVisibility=>AnnotationMethod=="SAM 辅助"?System.Windows.Visibility.Visible:System.Windows.Visibility.Collapsed;
    public System.Windows.Visibility TrackingToolsVisibility=>videoPath is not null||Text(currentMetadata,"video").Length>0?System.Windows.Visibility.Visible:System.Windows.Visibility.Collapsed;
    partial void OnAnnotationMethodChanged(string value){OnPropertyChanged(nameof(SamToolsVisibility));OnPropertyChanged(nameof(YoloToolsVisibility));}
    public string[] AnnotationMethods { get; }=["手工标注","SAM 辅助","YOLO 预标注"];
    public string SaveState=>Saving?"保存中…":Dirty?"待保存 · 待复核":"已保存";
    public string ConfirmLabel=>GetBoxes().Count==0?"确认无目标":"完成";
    partial void OnDirtyChanged(bool value){OnPropertyChanged(nameof(SaveState));NotifyProgress();}
    partial void OnSavingChanged(bool value)=>OnPropertyChanged(nameof(SaveState));
    partial void OnSearchChanged(string value)=>FilterImages();
    bool transitioning, starting;
    readonly List<JsonElement> earlyEvents=[];
    readonly Dictionary<int,List<Annotation>> drafts=[];
    Dictionary<string,object> advanced=[],augments=[],exportParams=new(){["imgsz"]=640,["opset"]=18,["dynamic"]=false,["simplify"]=true,["batch"]=1};
    public StudioViewModel()
    {
        ActionCommand=new AsyncRelayCommand<string>(RunAction);
        bridge.Event+=OnEvent;bridge.Log+=AppendLog;
        bridge.Faulted+=message=>{Busy=false;starting=false;VideoState="idle";earlyEvents.Clear();Status=message;};
    }
    public async Task Initialize()
    {
        await Safe(async()=>
        {
            bridge.Start();var hello=await bridge.Call("hello");settings=hello.GetProperty("settings").Clone();
            Brand=Text(settings,"brand","Label Once");LogoPath=Text(settings,"logo");SamSize=Number(settings,"sam_imgsz",1024);
            foreach(var s in settings.GetProperty("recent").EnumerateArray()){var rp=s.GetString()!;RecentProjects.Add(new(Path.GetFileName(rp.TrimEnd(Path.DirectorySeparatorChar)),rp));}
            advanced=Dictionary(hello.GetProperty("advanced"));augments=Dictionary(hello.GetProperty("augments"));
            Fill(Models,hello.GetProperty("models"));Fill(SamModels,hello.GetProperty("sam_models"));SelectedModel=Models.FirstOrDefault()??"";SelectedSam=SamModels.FirstOrDefault()??"";
            var prefs=hello.GetProperty("preferences");Acrylic=!prefs.TryGetProperty("acrylic",out var a)||a.GetBoolean();ShowHomeAtStartup=!prefs.TryGetProperty("show_home",out var homePref)||homePref.GetBoolean();MaterialChanged?.Invoke();Status="就绪 · 打开或新建项目";
        });
    }
    public async Task Safe(Func<Task> work)
    {
        try{await work();}catch(Exception exc){Status="操作失败："+exc.Message;AppendLog(exc.ToString());}
    }
    void AppendLog(string text){Log=(Log+text+Environment.NewLine);if(Log.Length>100000)Log=Log[^80000..];}
    public async Task OpenProject(string path)
    {
        path=Path.GetFullPath(path);
        if(!await Save())return;
        var snapshot=await bridge.Call("project.open",new{path});Project=snapshot.GetProperty("project").GetString()!;ProjectTitle=Path.GetFileName(Project);CurrentName="";Dirty=false;videoPath=videoSession=trackingSession=null;drafts.Clear();documentGeneration++;
        CanvasAction?.Invoke("clear-document");ApplySnapshot(snapshot);Status="项目已打开";HasProject=true;RememberRecent(path);Go(PageLibrary);
        var workspace=snapshot.GetProperty("workspace");var remembered=Text(workspace,"image");batchId=Text(workspace,"batch");Filter=Text(workspace,"filter","全部素材");Search=Text(workspace,"search");SelectedBatch=Text(workspace,"selected_batch","全部批次");if(!Batches.Contains(SelectedBatch))SelectedBatch="全部批次";SelectedClass=Math.Max(0,Classes.IndexOf(Text(workspace,"class_name")));AnnotationMethod=Text(workspace,"method","手工标注");FilterImages();
        if(batchId.Length>0&&!Batches.Contains(batchId)){batchId="";if(Filter=="当前批次")Filter="全部素材";else FilterImages();}
        if(allImages.Any(x=>x.Name==remembered))await OpenImage(remembered);
    }
    void RememberRecent(string path)
    {
        var existing=RecentProjects.FirstOrDefault(r=>r.Path==path);
        if(existing is not null)RecentProjects.Remove(existing);
        RecentProjects.Insert(0,new RecentEntry(Path.GetFileName(path.TrimEnd(Path.DirectorySeparatorChar)),path));
        while(RecentProjects.Count>10)RecentProjects.RemoveAt(RecentProjects.Count-1);
    }
    public async Task<bool> EnsureProject()
    {
        if(Project.Length>0)return true;
        var path=UserDialogs.Folder("选择项目目录（新项目会创建标准目录）");
        if(path is null)return false;
        await OpenProject(path);
        return Project.Length>0;
    }
    public async Task ImportChained()
    {
        var files=UserDialogs.Files("导入图片和相邻 YOLO 标签","图片|*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.webp",true);
        await ImportChainedFiles(files,true);
    }
    public async Task ImportChainedFiles(string[] files,bool navigate)
    {
        if(files.Length==0)return;
        if(!await EnsureProject())return;
        await Import(files);
        if(navigate){if(Images.Count>0&&CurrentName.Length==0)await OpenImage(Images[0].Name);Go(PageAnnotation);}
    }
    public async Task VideoChained()
    {
        var vpaths=UserDialogs.Files("选择视频","视频|*.mp4;*.avi;*.mov;*.mkv;*.webm");
        if(vpaths.Length==0)return;
        if(!await EnsureProject())return;
        await OpenVideo(vpaths[0]);
    }
    void ApplySnapshot(JsonElement s)
    {
        Classes.Clear();foreach(var n in s.GetProperty("classes").EnumerateArray())Classes.Add(n.GetString()!);
        allImages=s.GetProperty("images").EnumerateArray().Select(i=>new ImageEntry(Text(i,"name"),Text(i,"path"),Text(i,"status"),Text(i,"batch"),SourceDescription(i.GetProperty("metadata")))).ToList();
        var selection=SelectedBatch;Batches.Clear();Batches.Add("全部批次");foreach(var batch in allImages.Select(i=>i.Batch).Where(b=>!string.IsNullOrEmpty(b)).Distinct())Batches.Add(batch!);SelectedBatch=Batches.Contains(selection)?selection:"全部批次";
        Fill(Models,s.GetProperty("models"));Fill(SamModels,s.GetProperty("sam_models"));Fill(Versions,s.GetProperty("versions"));
        if(!Models.Contains(SelectedModel))SelectedModel=Models.FirstOrDefault()??"";if(!SamModels.Contains(SelectedSam))SelectedSam=SamModels.FirstOrDefault()??"";
        if(!Versions.Contains(SelectedVersion))SelectedVersion=Text(s,"active_version");
        if(s.TryGetProperty("release_gate",out var gate)&&gate.ValueKind==JsonValueKind.Object&&gate.TryGetProperty("passed",out var passedEl))
            GateStatusText=(gate.TryGetProperty("stale",out var staleEl)&&staleEl.GetBoolean())?"上次门禁结果已过期，请重新检查":"上次门禁："+(passedEl.GetBoolean()?"通过":"未通过");
        else GateStatusText="尚未运行门禁检查";
        experiments=s.GetProperty("experiments").EnumerateArray().Select(Dictionary).ToList();Experiments.Clear();foreach(var e in experiments)Experiments.Add(e);
        var st=s.GetProperty("stats");StatsText=$"{Number(st,"total")} 张素材 · {allImages.Count(i=>i.Status=="pending")} 张待完成 · {Classes.Count} 个类别";FilterImages();
    }
    public async Task Refresh(){if(Project.Length>0)ApplySnapshot(await bridge.Call("project.snapshot",new{project=Project}));}
    partial void OnFilterChanged(string value)=>FilterImages();
    partial void OnSelectedClassChanged(int value){}
    partial void OnCurvePathChanged(string value)=>RefreshCurve(value);
    void RefreshCurve(string path)
    {
        if(!File.Exists(path)){CurveImage=null;return;}
        try{using var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite);var bitmap=new BitmapImage();bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.StreamSource=stream;bitmap.EndInit();bitmap.Freeze();CurveImage=bitmap;}
        catch(IOException){/* The next epoch or completion retries a plot still being written. */}
        catch(NotSupportedException){}
    }
    void FilterImages(){Images.Clear();foreach(var i in allImages.Where(i=>i.Name.Contains(Search,StringComparison.OrdinalIgnoreCase)).Where(i=>SelectedBatch=="全部批次"||i.Batch==SelectedBatch).Where(i=>Filter switch{"待完成"=>i.Status is "pending" or "legacy","已完成"=>i.Status=="confirmed","已驳回"=>i.Status=="rejected","当前批次"=>i.Batch==batchId,"存在问题"=>problemImages.Contains(i.Name),_=>true}))Images.Add(i);OnPropertyChanged(nameof(CurrentPosition));NotifyProgress();}
    public void AnnotationChanged()
    {
        // A manual edit invalidates both an in-flight result and the latest queued
        // request.  The user can still issue a fresh Q/E prompt afterwards.
        documentGeneration++;promptRevision++;queuedSam=null;
        Dirty=true;SyncObjects();OnPropertyChanged(nameof(ConfirmLabel));NotifyProgress();
    }
    public void InvalidateSamRequests(){documentGeneration++;promptRevision++;queuedSam=null;}
    public void SyncObjects(){Objects.Clear();var boxes=GetBoxes();for(int i=0;i<boxes.Count;i++){var b=boxes[i];Objects.Add(new(i,b.TargetId,b.ClassId<Classes.Count?Classes[b.ClassId]:$"class_{b.ClassId}",b.Origin));}}
    public async Task<bool> Save(bool confirm=false)
    {
        if(Saving)return false;
        if(!await ResolveCandidate())return false;
        if(CurrentName.Length==0)return true;
        Saving=true;
        try{await SaveWorkspace();}catch(Exception exc){Status="工作区保存失败："+exc.Message;Saving=false;return false;}
        if(videoPath is not null)
        {
            if(!Dirty){Saving=false;return true;}
            try
            {
                Saving=true;var generation=documentGeneration;var video=videoPath;var frame=Frame;
                var boxes=GetBoxes();
                await bridge.Call("video.draft.save",new{project=Project,video,frame,boxes});
                if(generation!=documentGeneration||video!=videoPath||frame!=Frame){Status="视频编辑已变化，请再次保存";return false;}
                Dirty=false;Status="视频关键帧草稿已保存";return true;
            }
            catch(Exception exc){Status="视频草稿保存失败，编辑已保留："+exc.Message;return false;}
            finally{Saving=false;}
        }
        if(!Dirty&&!confirm){Saving=false;return true;}
        try
        {
            Saving=true;
            var generation=documentGeneration;
            var saved=await bridge.Call("annotation.save",new{project=Project,name=CurrentName,boxes=GetBoxes(),confirm,expected_revision=annotationRevision});annotationRevision=Number(saved,"revision");
            if(generation!=documentGeneration){Status="编辑已变化，请再次保存";return false;}
            var index=allImages.FindIndex(i=>i.Name==CurrentName);if(index>=0)allImages[index]=allImages[index] with {Status=confirm?"confirmed":"pending"};
            Dirty=false;NotifyProgress();
            Status=confirm?"已完成并保存":"标注已保存";return true;
        }
        catch(Exception exc){Status="保存失败，编辑已保留。可点击保存重试："+exc.Message;AppendLog(exc.ToString());return false;}
        finally{Saving=false;}
    }
    public async Task OpenImage(string name)
    {
        if(transitioning||Busy)return;transitioning=true;
        try
        {
            if(!await Save())return;
            NewSamTarget();long generation=++documentGeneration;string project=Project;
            var image=await bridge.Call("annotation.load",new{project,name});
            if(project!=Project||generation!=documentGeneration)return;
            videoPath=null;CurrentName=name;Dirty=false;annotationRevision=Number(image,"revision");currentMetadata=image.GetProperty("metadata").Clone();OnPropertyChanged(nameof(TrackingToolsVisibility));
            var boxes=JsonSerializer.Deserialize<List<Annotation>>(image.GetProperty("boxes"))!;
            DocumentChanged?.Invoke(new(Text(image,"path"),Text(image,"source"),Number(image,"width"),Number(image,"height"),Number(image,"orientation",1),boxes,false));SyncObjects();OnPropertyChanged(nameof(ConfirmLabel));Status="已打开图片："+name;
            await SaveWorkspace();
        }
        finally{transitioning=false;}
    }
    Task<JsonElement> SaveWorkspace()=>bridge.Call("workspace.save",new{project=Project,state=new{schema=1,image=videoPath is null?CurrentName:"",filter=Filter,batch=batchId,selected_batch=SelectedBatch,search=Search,class_name=Classes.ElementAtOrDefault(SelectedClass),method=AnnotationMethod}});
    public async Task Navigate(int step)
    {
        if(transitioning||Busy)return;
        if(videoPath is not null){await VideoFrame(Frame+step);return;}
        // Sidebar search/status filters narrow the visible list, but review navigation
        // must still visit every image in the selected batch.
        var list=ReviewImages.ToList();int index=list.FindIndex(x=>x.Name==CurrentName);if(list.Count==0)return;
        await OpenImage(list[Math.Clamp(index+step,0,list.Count-1)].Name);
    }
    public async Task ConfirmNext()
    {
        if(transitioning||Busy||videoPath is not null)return;
        transitioning=true;string nextName="";
        try
        {
            if(!await Save(true))return;
            await Refresh();
            nextName=ReviewImages.FirstOrDefault(i=>i.Status is "pending" or "legacy")?.Name??"";
        }
        finally{transitioning=false;}
        if(nextName.Length>0){await OpenImage(nextName);Status="已确认，已跳到下一张待完成";return;}
        Status=ReviewCompleted>=ReviewTotal&&ReviewTotal>0?"本批次复核完成":$"当前图片已完成；批次内还有 {ReviewTotal-ReviewCompleted} 张待完成";
    }
    public async Task OpenVideo(string path)
    {
        if(!await Save())return;NewSamTarget();var image=await bridge.Call("video.open",new{project=Project,path});
        videoPath=path;CurrentSourcePath=Path.GetFullPath(path);videoSession=Text(image,"session");drafts.Clear();CurrentName=Path.GetFileName(path);documentGeneration++;Frame=0;OnPropertyChanged(nameof(TrackingToolsVisibility));TotalFrames=Number(image,"total");VideoState="idle";trackingSession=null;VideoName=Path.GetFileName(path);VideoProgressFrame=0;VideoProgressTotal=TotalFrames;
        var draft=await bridge.Call("video.draft.load",new{project=Project,video=path,frame=0});ShowVideo(image,JsonSerializer.Deserialize<List<Annotation>>(draft.GetProperty("boxes"))!);Go(PageAnnotation);
        Status=$"已载入视频 {VideoName} · 在视频任务栏设置参数后启动";
    }
    public async Task VideoFrame(int frame)
    {
        if(Busy)return;
        if(transitioning||videoPath is null||frame<0||frame>=TotalFrames)return;transitioning=true;
        try
        {
            if(!await Save())return;NewSamTarget();drafts[Frame]=GetBoxes().Select(b=>b.Copy()).ToList();var session=videoSession;long generation=++documentGeneration;
            var image=await bridge.Call("video.frame",new{project=Project,session,frame});
            if(session!=videoSession||generation!=documentGeneration)return;
            Frame=Number(image,"frame");var draft=await bridge.Call("video.draft.load",new{project=Project,video=videoPath,frame=Frame});ShowVideo(image,JsonSerializer.Deserialize<List<Annotation>>(draft.GetProperty("boxes"))!);
        }finally{transitioning=false;}
    }
    void ShowVideo(JsonElement image,List<Annotation> boxes)
    {
        DocumentChanged?.Invoke(new(Text(image,"path"),videoSession??videoPath!,Number(image,"width"),Number(image,"height"),1,boxes,true));Dirty=false;SyncObjects();Status=$"第 {Frame+1}/{TotalFrames} 帧 · 同视频保留视角";
    }
    readonly List<double[]> samPoints=[];
    readonly List<int> samLabels=[];
    double[]? samBox, samRoi;
    string samObject=Guid.NewGuid().ToString();
    long promptRevision;
    bool samRunning;
    Dictionary<string,object?>? queuedSam;
    [ObservableProperty] bool samWorking;
    [ObservableProperty] double contourPrecision=1;
    partial void OnContourPrecisionChanged(double value)=>_=Safe(async()=>
    {
        if(videoPath is not null||CurrentName.Length==0||Busy)return;
        if(!double.IsFinite(value)||value<=0)throw new InvalidOperationException("轮廓误差必须为正数");
        promptRevision++;queuedSam=null;long generation=documentGeneration;var name=CurrentName;
        var result=await bridge.Call("annotation.simplify",new{project=Project,name,boxes=GetBoxes(),epsilon=value});
        if(generation!=documentGeneration||name!=CurrentName||value!=ContourPrecision)return;
        PendingSam=JsonSerializer.Deserialize<List<Annotation>>(result.GetProperty("boxes"))!;CanvasAction?.Invoke("replace-candidate");
    });
    public Func<int> GetSamLabel { get; set; }=()=>1;
    public void NewSamTarget()
    {
        promptRevision++;queuedSam=null;samPoints.Clear();samLabels.Clear();samBox=samRoi=null;samObject=Guid.NewGuid().ToString();
    }
    public async Task SetSamState(SamPromptState state,bool infer)
    {
        promptRevision++;queuedSam=null;samObject=state.ObjectId;samPoints.Clear();samPoints.AddRange(state.Points);
        samLabels.Clear();samLabels.AddRange(state.Labels);samBox=state.Box;samRoi=state.Roi;
        if(infer&&(!Busy||VideoState=="paused")&&CurrentName.Length>0)await QueueSam();
    }
    public async Task SetSamRoi(double[] roi){samRoi=roi;promptRevision++;await QueueSam();}
    public async Task Sam(double[] prompt,bool point)
    {
        if(Busy||videoPath is not null||CurrentName.Length==0)return;
        if(Classes.Count==0){await RunAction("classes");return;}
        if(point){samPoints.Add(prompt);samLabels.Add(GetSamLabel());}else samBox=prompt;
        await QueueSam();
    }
    async Task QueueSam()
    {
        if(!double.IsFinite(ContourPrecision)||ContourPrecision<=0)throw new InvalidOperationException("轮廓误差必须为正数");
        if(samBox is null&&!samLabels.Contains(1))return;
        queuedSam=new(){["project"]=Project,["name"]=CurrentName,["model"]=SelectedSam,["class_id"]=Math.Max(0,SelectedClass),["video_session"]=videoSession,["frame"]=Frame,["pause_token"]=pauseToken,
            ["device"]=Device,["imgsz"]=SamSize,["points"]=samPoints.Select(p=>(double[])p.Clone()).ToArray(),["labels"]=samLabels.ToArray(),
            ["bbox"]=samBox,["roi"]=samRoi,["object_id"]=samObject,["epsilon"]=ContourPrecision,["request"]=++promptRevision};
        if(samRunning)return;
        samRunning=true;SamWorking=true;
        try
        {
            while(queuedSam is { } request)
            {
                queuedSam=null;long revision=promptRevision,generation=documentGeneration;var name=CurrentName;
                Status="SAM 推理中 · 可继续添加 Q/E 提示";
                try
                {
                    var result=await bridge.Call("sam.segment",request);
                    if(revision!=promptRevision||name!=CurrentName||generation!=documentGeneration)continue;
                    PendingSam=[JsonSerializer.Deserialize<Annotation>(result.GetProperty("box"))!];CanvasAction?.Invoke("update-sam");Status="SAM 轮廓已更新 · Q 正点 / E 负点";
                }
                catch(Exception exc){Status="SAM 失败，保留最近轮廓与提示："+exc.Message;}
            }
        }
        finally{samRunning=false;SamWorking=false;}
    }
    async Task Start(string kind,Dictionary<string,object>? options=null)
    {
        if(Busy||SamWorking)throw new InvalidOperationException("已有任务运行，请等待当前 SAM 请求结束");
        starting=true;Busy=true;Progress=0;taskKind=kind;taskSucceeded=false;importedNames=[];firstProblem=null;
        progressMarks.Clear();VideoProgressFrame=0;VideoProgressTotal=0;
        if(kind=="train"){CurvePath="";CurveImage=null;EpochMetrics=[];}
        try
        {
            var task=await bridge.Call("task.start",new{project=Project,kind,options=options??[]});ActiveRun=Text(task,"run");trackingSession=Text(task,"session");Status="任务运行中："+kind;
        }
        catch{Busy=false;throw;}
        finally{starting=false;}
        foreach(var e in earlyEvents.ToArray())OnEvent(e);earlyEvents.Clear();
    }
    void OnEvent(JsonElement e)
    {
        if(starting){earlyEvents.Add(e.Clone());return;}
        if(Text(e,"project")!=Project||Text(e,"run")!=ActiveRun)return;
        string kind=Text(e,"event");
        if(kind=="progress"){Progress=e.GetProperty("value").GetDouble();Status=Text(e,"text");
            if(e.TryGetProperty("total",out var total)&&total.TryGetInt32(out var totalCount)&&totalCount>0)VideoProgressTotal=totalCount;
            if(e.TryGetProperty("frame",out var fr)&&fr.TryGetInt32(out var frameIndex))VideoProgressFrame=Math.Max(VideoProgressFrame,frameIndex);}
        if(kind=="epoch")
        {
            var metrics=e.GetProperty("metrics");
            double Metric(string key)=>metrics.TryGetProperty(key,out var v)&&v.TryGetDouble(out var d)?d:double.NaN;
            EpochMetrics=EpochMetrics.Append(new TrainingEpoch(Number(e,"epoch"),Metric("val/box_loss"),Metric("metrics/mAP50(B)"))).ToArray();
            var curve=Path.Combine(ActiveRun,"train","results.png");CurvePath=curve;RefreshCurve(curve);
        }
        if(kind is "tracking_frame" or "tracking_state")HandleTracking(e);
        if(kind=="error"){taskSucceeded=false;VideoState="failed";}
        if(kind=="cancelled"){taskSucceeded=false;VideoState="cancelled";}
        if(kind=="error")Status="任务失败："+Text(e,"message");
        if(kind=="cancelled")Status="任务已停止，输出已保留";
        if(kind=="result")
        {
            taskSucceeded=true;var r=e.GetProperty("result");ResultJson=JsonSerializer.Serialize(r,new JsonSerializerOptions{WriteIndented=true});
            if(taskKind=="model_info"){_=Safe(()=>PrelabelMapping(r));}
            if(r.TryGetProperty("outputs",out var outputs)){PreviewPath=outputs.EnumerateArray().Select(x=>x.GetString()!).FirstOrDefault(p=>Path.GetExtension(p) is ".jpg" or ".png")??"";}
            if(r.TryGetProperty("detections",out var rows)){Detections.Clear();foreach(var row in rows.EnumerateArray())Detections.Add(Dictionary(row));}
            if(r.TryGetProperty("names",out var names))importedNames=(names.ValueKind==JsonValueKind.Array
                ?names.EnumerateArray().Select(n=>n.GetString()!)
                // model_info 的 names 是 {索引: 类名} 对象（ultralytics 原生形态），按数字键排序还原
                :names.EnumerateObject().OrderBy(p=>int.TryParse(p.Name,out var idx)?idx:int.MaxValue).Select(p=>p.Value.GetString()!)).ToArray();
            if(taskKind=="segment_dataset"&&r.TryGetProperty("issues",out var issues)&&issues.GetArrayLength()>0){Status="分割导出被阻止，请修正问题图片";UserDialogs.Form("分割导出问题",new(){["问题清单"]=string.Join("\n",issues.EnumerateArray().Select(i=>Text(i,"name")+"："+Text(i,"reason")))},true);}
            if(taskKind=="train"){var output=Text(r,"output");CurvePath=Path.Combine(output,"results.png");RefreshCurve(CurvePath);}
            if(r.TryGetProperty("issues",out var foundIssues))foreach(var issue in foundIssues.EnumerateArray()){var issueName=Text(issue,"name");problemImages.Add(issueName);firstProblem??=issueName;}
            if(r.TryGetProperty("conflicts",out var conflicts))foreach(var conflict in conflicts.EnumerateArray()){problemImages.Add(conflict.GetString()!);firstProblem??=conflict.GetString();}
            Status=firstProblem is null?"任务完成 · 结果保存在 "+ActiveRun:"任务完成，存在需人工处理的问题图片";
            if(taskKind=="dataset_merge"&&r.TryGetProperty("version",out var mergedVersion))
                Status=$"整合完成：数据集版本 {mergedVersion.GetString()!} 已激活，共 {Number(r,"total")} 张样本";
            if(taskKind=="gate")ShowGateResult(r);
        }
        if(kind=="finished"){Busy=false;_=Safe(FinishTask);}
        AppendLog(e.ToString());
    }
    async Task FinishTask()
    {
        string completedKind=taskKind;bool succeeded=taskSucceeded;
        var names=importedNames;importedNames=[];
        // 等“结束并复核”在途的 SAM 轮廓收尾，否则自动导入链会被 Busy 拒绝并把该环节丢掉
        for(int i=0;i<200&&SamWorking;i++)await Task.Delay(50);
        await Refresh();
        if(!succeeded){if(completedKind=="tracking"){videoPath=null;Dirty=false;if(allImages.Any(i=>i.Name==CurrentName))await OpenImage(CurrentName);}return;}
        // Video products flow straight into the review batch, like the legacy Qt chain.
        if(completedKind is "extract" or "tracking"){VideoState="completed";await Start("import_video",new(){["source_run"]=ActiveRun});return;}
        if(completedKind=="import_video"&&names.Length>0)await CompleteImport(names);
        if(firstProblem is { } problem){Search="";SelectedBatch="全部批次";Filter="存在问题";await OpenImage(problem);Go(PageAnnotation);Status="已定位问题图片；导出问题见日志，跟踪候选可从“更多”菜单查看";}
    }
    void ShowGateResult(JsonElement summary)
    {
        bool passed=summary.TryGetProperty("passed",out var ok)&&ok.GetBoolean();
        var message=passed?"✅ 发布门禁通过":"❌ 发布门禁未通过";
        if(!passed&&summary.TryGetProperty("failures",out var failures))
            message+='\n'+string.Join('\n',failures.EnumerateArray().Select(f=>f.GetString()!).Where(s=>s.Length>0));
        if(summary.TryGetProperty("warnings",out var warnings)&&warnings.GetArrayLength()>0)
            message+="\n\n提示：\n"+string.Join('\n',warnings.EnumerateArray().Select(f=>f.GetString()!));
        if(!passed&&summary.TryGetProperty("per_class",out var rows))
        {
            var worst=rows.EnumerateArray()
                .Where(x=>x.TryGetProperty("passed",out var item)&&!item.GetBoolean())
                .Select(x=>$"  {Text(x,"cls")}：AP50 {Number(x,"old_ap50",1):0.00000} → {Number(x,"new_ap50",0):0.00000}")
                .Take(6).ToArray();
            if(worst.Length>0)message+="\n逐类跌幅（前 6）：\n"+string.Join('\n',worst);
        }
        if(summary.TryGetProperty("report",out var report)&&report.ValueKind==JsonValueKind.String)
            message+=$"\n\n报告：{report.GetString()!}";
        System.Windows.MessageBox.Show(message,"发布门禁",System.Windows.MessageBoxButton.OK,
            passed?System.Windows.MessageBoxImage.Information:System.Windows.MessageBoxImage.Warning);
    }
    async Task ChooseMethod()
    {
        var choice=UserDialogs.AnnotationMethod(AnnotationMethod);
        if(choice is null)return;
        AnnotationMethod=choice;
        if(AnnotationMethod=="YOLO 预标注")await RunAction("prelabel");else CanvasAction?.Invoke(AnnotationMethod=="SAM 辅助"?"sam-point":"select");
    }
    async Task CompleteImport(string[] names)
    {
        if(names.Length==0)return;
        Search="";SelectedBatch="全部批次";var name=names[0];batchId=allImages.First(i=>i.Name==name).Batch;Filter="当前批次";FilterImages();
        await OpenImage(name);Go(PageAnnotation);
    }
    public List<Annotation> PendingSam { get; private set; }=[];
    public async Task<int> EnsureClass(string name)
    {
        var result=await bridge.Call("classes.ensure",new{project=Project,name,pause_token=pauseToken});
        Classes.Clear();foreach(var value in result.GetProperty("classes").EnumerateArray())Classes.Add(value.GetString()!);
        SelectedClass=Number(result,"class_id");return SelectedClass;
    }
    public int TrackingNextId { get; private set; }
    void HandleTracking(JsonElement e)
    {
        if(Text(e,"session")!=trackingSession)return;
        TrackingNextId=Number(e,"next_id",GetNextId());CanvasAction?.Invoke("tracking-next-id");
        int f=Number(e,"frame",-1);if(f<Frame&&VideoState!="starting")return;
        if(Text(e,"event")=="tracking_frame")
        {
            string path=Text(e,"path");var boxes=e.GetProperty("boxes").EnumerateObject().Select(p=>{var b=JsonSerializer.Deserialize<Annotation>(p.Value)!;b.TargetId=int.Parse(p.Name);return b;}).ToList();
            using var stream=File.OpenRead(path);var decoder=System.Windows.Media.Imaging.BitmapDecoder.Create(stream,System.Windows.Media.Imaging.BitmapCreateOptions.None,System.Windows.Media.Imaging.BitmapCacheOption.OnLoad);var bmp=decoder.Frames[0];
            Frame=f;VideoProgressFrame=Math.Max(VideoProgressFrame,f);DocumentChanged?.Invoke(new(path,videoPath??videoSession??trackingSession!,bmp.PixelWidth,bmp.PixelHeight,1,boxes,true));SyncObjects();Dirty=false;CanvasAction?.Invoke("tracking-next-id");
        }
        else
        {
            var state=Text(e,"state");
            if(state=="paused"&&Frame!=f)return;
            if(state=="paused"&&Text(e,"pause_token").Length==0){VideoState="failed";Status="暂停确认缺少有效令牌，请停止任务后恢复";return;}
            pauseToken=Text(e,"pause_token");waitingAction="";VideoState=state;Frame=f;
            if(state=="paused")
            {
                PendingSam=e.GetProperty("targets").EnumerateObject().Select(p=>{var t=p.Value;var xy=t.GetProperty("box").EnumerateArray().Select(x=>x.GetDouble()).ToArray();return new Annotation{TargetId=int.Parse(p.Name),ObjectId=Text(t,"object_id",Guid.NewGuid().ToString()),ClassId=Number(t,"cls"),X1=xy[0],Y1=xy[1],X2=xy[2],Y2=xy[3],Origin="AI",Polygons=t.TryGetProperty("polygons",out var poly)?JsonSerializer.Deserialize<List<List<double[]>>>(poly):null,Holes=t.TryGetProperty("holes",out var holes)?JsonSerializer.Deserialize<List<List<double[]>>>(holes):null};}).ToList();CanvasAction?.Invoke("tracking-targets");
                if(e.TryGetProperty("failures",out var failures)&&failures.ValueKind==JsonValueKind.Object&&failures.GetRawText()!="{}")
                    Status="目标漂移，已自动暂停 · "+string.Join(" · ",failures.EnumerateObject().Select(f=>{var id=int.TryParse(f.Name,out var parsed)?parsed:-1;var cls=PendingSam.FirstOrDefault(a=>a.TargetId==id);return $"目标 {f.Name}{(cls is not null&&cls.ClassId<Classes.Count?"（"+Classes[cls.ClassId]+"）":"")}：{f.Value.GetString()}";}))+"；修正后点“提交纠偏”继续";
                else Status="已暂停 · 画布可直接修正，点“提交纠偏”继续";
            }
        }
    }
    string prelabelModel="";
    async Task PrelabelMapping(JsonElement result)
    {
        // Completion is emitted immediately before 'finished'; wait for supervisor release.
        for(int i=0;Busy&&i<40;i++)await Task.Delay(50);
        var names=result.GetProperty("names").EnumerateObject().ToDictionary(p=>p.Name,p=>p.Value.GetString()!);
        var mapping=UserDialogs.Form("AI 类别映射",names.ToDictionary(p=>$"{p.Key} · {p.Value}",p=>Classes.Contains(p.Value)?Classes.IndexOf(p.Value).ToString():"-1"),explanation:"填写项目类别编号；-1 忽略。项目类别："+string.Join("，",Classes.Select((n,i)=>$"{i}={n}")));
        if(mapping is null)return;var values=mapping.ToDictionary(p=>p.Key.Split(' ')[0],p=>int.Parse(p.Value));
        if(values.Values.Any(v=>v < -1 || v>=Classes.Count))throw new InvalidOperationException("映射编号必须是已有项目类别或 -1");
        await Start("prelabel",new(){["model"]=prelabelModel,["mapping"]=values,["names"]=Images.Select(i=>i.Name).ToArray(),["replace"]=false,["conf"]=Conf,["iou"]=Iou,["device"]=Device});
    }
    public void Go(int page){Page=page;CanvasAction?.Invoke("stop-navigation");PageRequested?.Invoke(page);}
    public async Task RunAction(string? action)=>await Safe(async()=>
    {
        switch(action)
        {
            case "new":case "open":{var path=UserDialogs.Folder("选择项目目录（新项目会创建标准目录）");if(path is not null)await OpenProject(path);break;}
            case "library":if(!await Save())return;Go(PageLibrary);break;
            case "home":Go(PageHome);break;
            case "home-import":await ImportChained();break;
            case "annotation":if(Images.Count>0&&CurrentName.Length==0)await OpenImage(Images[0].Name);Go(PageAnnotation);break;
            case "video":case "video-choose":case "home-video":await VideoChained();break;
            case "train-page":if(!await Save())return;Go(PageTraining);break;
            case "model-page":if(!await Save())return;Go(PageModel);break;
            case "settings":if(!await Save())return;Go(PageSettings);break;
            case "segment-dataset":
                if(!await Save())return;var topology=UserDialogs.Form("导出分割数据集",new(){["拆分多连通区域（yes / no）"]="no",["填充孔洞（yes / no）"]="no"},explanation:"默认保留实例与孔洞语义；标准 YOLO 无法表达的形状会阻止导出并列出问题。选择 yes 会明确改变导出拓扑，内部标注保留原形状。");
                if(topology is not null)await Start("segment_dataset",new(){["split_components"]=topology.Values.First().Equals("yes",StringComparison.OrdinalIgnoreCase),["fill_holes"]=topology.Values.Last().Equals("yes",StringComparison.OrdinalIgnoreCase)});break;
            case "track-samples":
                if(!await Save())return;
                string sourceVideo=Text(currentMetadata,"video"),sampleRun=Text(currentMetadata,"run");
                if(!File.Exists(sourceVideo))throw new InvalidOperationException("原视频不存在；图片仍可标注和导出，请重新关联原视频后跟踪");
                var targets=GetBoxes();if(targets.Count==0)throw new InvalidOperationException("请先标出目标");
                int next=targets.Max(b=>b.TargetId)+1;foreach(var b in targets)if(b.TargetId<0)b.TargetId=next++;
                if(targets.Select(b=>b.TargetId).Distinct().Count()!=targets.Count||next>32)throw new InvalidOperationException("目标 ID 重复或超过 32 个终身 ID");
                videoPath=sourceVideo;CurrentSourcePath=sourceVideo;Frame=Number(currentMetadata,"frame");videoSession=sourceVideo;VideoState="starting";VideoName=Path.GetFileName(sourceVideo);
                try{await Start("tracking",new(){["video"]=sourceVideo,["sample_run"]=sampleRun,["start_frame"]=Frame,["frame_step"]=FrameStep,["model"]=SelectedSam,["device"]=Device,["imgsz"]=SamSize,["targets"]=targets.Select(b=>new{id=b.TargetId,cls=b.ClassId,object_id=b.ObjectId,box=new[]{b.X1,b.Y1,b.X2,b.Y2},polygons=b.Polygons,holes=b.Holes}).ToArray(),["next_id"]=targets.Max(b=>b.TargetId)+1});}
                catch{videoPath=null;VideoState="idle";throw;}break;
            case "tracking-candidate":
                if(!await Save())return;var candidate=await bridge.Call("tracking.candidate",new{project=Project,run=ActiveRun,name=CurrentName});
                PendingSam=JsonSerializer.Deserialize<List<Annotation>>(candidate.GetProperty("boxes"))!;
                if(UserDialogs.Confirm($"当前图片有 {PendingSam.Count} 个跟踪候选。用候选替换当前标注？可撤销，应用后需要重新复核。"))CanvasAction?.Invoke("replace-candidate");break;
            case "method":await ChooseMethod();break;
            case "sam-new":CanvasAction?.Invoke("sam-new");break;
            case "sam-clear":NewSamTarget();CanvasAction?.Invoke("sam-clear");break;
            case "import":{var files=UserDialogs.Files("导入图片和相邻 YOLO 标签","图片|*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.webp",true);if(files.Length>0)await Import(files);break;}
            case "merge":{var folder=UserDialogs.Folder("合并素材文件夹");if(folder is not null)await Import([folder]);break;}
            case "save":await Save();break;
            case "confirm":await ConfirmNext();break;
            case "accept-all":
            {
                if(transitioning||Busy||videoPath is not null)break;
                transitioning=true;string nextName="";
                try
                {
                    if(!await Save())return;
                    var names=ReviewImages.Where(i=>i.Status is "pending" or "legacy").Select(i=>i.Name).ToArray();
                    if(names.Length==0){Status="当前集合没有待完成图片";return;}
                    var report=await bridge.Call("review.pending",new{project=Project,names});
                    var items=report.GetProperty("items").EnumerateArray().Select(item=>(name:Text(item,"name"),
                        missing:item.GetProperty("missing").GetBoolean(),empty:item.GetProperty("empty").GetBoolean(),
                        unknown:item.GetProperty("unknown").GetBoolean())).ToList();
                    var blocked=items.Where(i=>i.missing||i.unknown).ToList();
                    var acceptedNames=items.Where(i=>!i.missing&&!i.unknown).Select(i=>i.name).ToArray();
                    if(acceptedNames.Length==0){Status=$"{blocked.Count} 张图片缺标签或含未知类别，无法批量接受";return;}
                    var question=$"将接受 {acceptedNames.Length} 张待完成图片（其中 {items.Count(i=>i.empty)} 张空标签将作为负样本）";
                    if(blocked.Count>0)question+= $"。跳过 {blocked.Count} 张问题图片：{string.Join("，",blocked.Select(i=>i.name).Take(6))}{(blocked.Count>6?"…":"")}";
                    if(!UserDialogs.Confirm(question+"？"))return;
                    await bridge.Call("review.confirm",new{project=Project,names=acceptedNames});
                    await Refresh();
                    nextName=ReviewImages.FirstOrDefault(i=>i.Status is "pending" or "legacy")?.Name??"";
                    Status=$"已批量接受 {acceptedNames.Length} 张";
                }
                finally{transitioning=false;}
                if(nextName.Length>0)await OpenImage(nextName);
                break;
            }
            case "review-reject":
            {
                if(transitioning||Busy||videoPath is not null||CurrentName.Length==0)break;
                transitioning=true;string nextName="";
                try
                {
                    var form=UserDialogs.Form("驳回当前图片",new(){["原因"]="漏标或错标"});
                    if(form is null)return;
                    await bridge.Call("review.reject",new{project=Project,names=new[]{CurrentName},reason=form.Values.First()});
                    await Refresh();
                    nextName=ReviewImages.FirstOrDefault(i=>i.Status is "pending" or "legacy")?.Name??"";
                    Status="已驳回，需重新标注后再完成";
                }
                finally{transitioning=false;}
                if(nextName.Length>0)await OpenImage(nextName);
                break;
            }
            case "review-batch":
                Search="";SelectedBatch="全部批次";Filter="待完成";FilterImages();
                if(CurrentName.Length==0&&Images.Count>0)await OpenImage(Images[0].Name);
                Go(PageAnnotation);break;
            case "previous":await Navigate(-1);break;
            case "next":await Navigate(1);break;
            case "classes":
                if(!await Save())return;
                var c=UserDialogs.Form("管理类别",new(){["类别名称，每行一个"]=string.Join('\n',Classes)},true,"重排与重命名会同步现有标签并创建备份；删除的类别将移除相应标注。");
                if(c is not null)
                {
                    var names=c.Values.First().Split('\n').Select(n=>n.Trim()).Where(n=>n.Length>0).ToArray();
                    if(names.Length==0||names.Distinct().Count()!=names.Length)throw new InvalidOperationException("类别名称不能为空或重复");
                    var rows=Classes.Select((name,i)=>new{Key=$"{i} · {name}",Value=Array.IndexOf(names,name).ToString()}).ToDictionary(p=>p.Key,p=>p.Value);
                    var mapping=rows.Count==0?new Dictionary<string,string>():UserDialogs.Form("旧类别 → 新类别",rows,explanation:"填写新编号；-1 删除该旧类别的标注。重命名需指定新编号。新类别："+string.Join("，",names.Select((n,i)=>$"{i}={n}")));
                    if(mapping is null)return;
                    var values=mapping.ToDictionary(p=>p.Key.Split(' ')[0],p=>int.Parse(p.Value));
                    if(values.Values.Any(v=>v < -1||v>=names.Length))throw new InvalidOperationException("映射编号超出新类别范围");
                    await bridge.Call("classes.save",new{project=Project,names,mapping=values.Where(p=>p.Value>=0).ToDictionary()});await Refresh();if(videoPath is null&&CurrentName.Length>0)await OpenImage(CurrentName);
                }break;
            case "rename":
                if(!await Save())return;var rn=UserDialogs.Form("批量重命名",new(){["前缀"]="image_",["起始编号"]="1"});
                if(rn is not null){var preview=await bridge.Call("images.rename",new{project=Project,prefix=rn["前缀"],start=int.Parse(rn["起始编号"]),preview=true});if(UserDialogs.Confirm("将同步重命名图片、标签与复审记录：\n"+string.Join('\n',preview.EnumerateArray().Take(8)))){await bridge.Call("images.rename",new{project=Project,prefix=rn["前缀"],start=int.Parse(rn["起始编号"])});CurrentName="";Dirty=false;CanvasAction?.Invoke("clear-document");await Refresh();}}break;
            case "inspect":await Start("inspect_images",new(){["min_size"]=32});break;
            case "prelabel":if(!await Save())return;prelabelModel=SelectedModel;await Start("model_info",new(){["model"]=SelectedModel});break;
            case "clear-ai":CanvasAction?.Invoke("clear-ai");break;
            case "dataset":case "incremental":
                if(!await Save())return;var ratios=UserDialogs.Form("创建数据集版本",new(){["训练比例"]="0.7",["验证比例"]="0.2",["测试比例"]="0.1",["随机种子"]="42"},explanation:"仅纳入已完成样本；已完成的空标签作为负样本。待完成素材自动排除。");
                if(ratios is not null)await Start("dataset",new(){["ratios"]=new[]{double.Parse(ratios["训练比例"]),double.Parse(ratios["验证比例"]),double.Parse(ratios["测试比例"])},["seed"]=int.Parse(ratios["随机种子"]),["incremental"]=action=="incremental"});break;
            case "activate":await bridge.Call("dataset.activate",new{project=Project,version=SelectedVersion});await Refresh();break;
            case "dataset-merge":{
                if(!await Save())return;
                var spec=DatasetMergeDialog.DatasetSources(bridge.Call,Project,Versions.ToArray(),SelectedVersion);
                if(spec is not null)await Start("dataset_merge",spec);break;
            }
            case "advanced":{var a=UserDialogs.Parameters("高级训练参数",advanced);if(a is not null)advanced=a;break;}
            case "augments":{var a=UserDialogs.Parameters("数据增强",augments);if(a is not null)augments=a;break;}
            case "preset-save":await bridge.Call("preset.save",new{project=Project,@params=TrainParams()});Status="项目预设已保存";break;
            case "preset-load":{var p=await bridge.Call("preset.get",new{project=Project});Epochs=Number(p,"epochs",50);Batch=Number(p,"batch",16);Imgsz=Number(p,"imgsz",640);LearningRate=p.GetProperty("lr0").GetDouble();Device=Text(p,"device","0");var values=Dictionary(p);foreach(var k in advanced.Keys.ToArray())if(values.ContainsKey(k))advanced[k]=values[k];foreach(var k in augments.Keys.ToArray())if(values.ContainsKey(k))augments[k]=values[k];break;}
            case "defaults":Epochs=50;Batch=16;Imgsz=640;LearningRate=.001;var hello=await bridge.Call("hello");advanced=Dictionary(hello.GetProperty("advanced"));augments=Dictionary(hello.GetProperty("augments"));break;
            case "train":if(!await Save())return;if(Imgsz%32!=0)throw new InvalidOperationException("输入尺寸必须为 32 的倍数");await Start("train",new(){["model"]=SelectedModel,["params"]=TrainParams(),["dataset_version"]=SelectedVersion});break;
            case "train-resume":{if(!await Save())return;var checkpoint=LatestCheckpoint();if(checkpoint is null)throw new InvalidOperationException("没有找到 last.pt 检查点，无法续训");await Start("train",new(){["model"]=SelectedModel,["params"]=TrainParams(),["dataset_version"]=SelectedVersion,["resume"]=checkpoint});break;}
            case "gate":{
                var gateModel=UserDialogs.Files("选择候选模型权重","模型|*.pt;*.onnx;*.engine;*.torchscript").FirstOrDefault();
                if(gateModel is null)break;
                var golden=UserDialogs.Folder("选择冻结基准集 golden 目录（数据集版本文件夹，或其中 dataset.yaml / manifest.csv）");
                if(golden is null)break;
                string? baseline=null;
                if(UserDialogs.Confirm("是否同时对比基线模型（类表前缀校验 + 逐类 AP50 跌幅）？"))
                    baseline=UserDialogs.Files("选择基线模型权重（取消则跳过）","模型|*.pt;*.onnx;*.engine").FirstOrDefault();
                string? quantized=null;
                if(UserDialogs.Confirm("是否校验量化模型掉点？"))
                    quantized=UserDialogs.Files("选择量化模型权重（取消则跳过）","量化模型|*.onnx;*.engine").FirstOrDefault();
                var threshold=UserDialogs.Form("门禁阈值",new(){["mAP50 下限"]="0.50",["逐类 AP50 最大跌幅"]="0.03",["量化最大掉点"]="0.02"});
                if(threshold is null)break;
                await Start("gate",new Dictionary<string,object>{["model"]=gateModel,["golden"]=golden,["baseline"]=baseline??"",["quantized"]=quantized??"",
                    ["map50_min"]=double.Parse(threshold["mAP50 下限"]),
                    ["ap50_drop_max"]=double.Parse(threshold["逐类 AP50 最大跌幅"]),
                    ["quant_drop_max"]=double.Parse(threshold["量化最大掉点"])});break;
            }
            case "model-browse":{var f=UserDialogs.Files("选择 YOLO 模型","模型|*.pt;*.onnx;*.engine;*.torchscript;*.xml");if(f.Length>0){Models.Add(f[0]);SelectedModel=f[0];}break;}
            case "sam-browse":{var f=UserDialogs.Files("选择 SAM2 权重","权重|*.pt");if(f.Length>0){SamModels.Add(f[0]);SelectedSam=f[0];}break;}
            case "source-file":Source=UserDialogs.Files("选择推理输入").FirstOrDefault()??Source;break;
            case "source-folder":Source=UserDialogs.Folder("选择推理文件夹")??Source;PredictMode="batch";break;
            case "predict":await Start("predict",new(){["model"]=SelectedModel,["source"]=Source,["mode"]=PredictMode,["conf"]=Conf,["iou"]=Iou,["device"]=ModelDevice});break;
            case "evaluate":await Start("evaluate",new(){["model"]=SelectedModel,["dataset_version"]=SelectedVersion,["conf"]=Conf,["iou"]=Iou,["device"]=ModelDevice});break;
            case "export-params":{var p=UserDialogs.Parameters("模型导出参数",exportParams);if(p is not null)exportParams=p;break;}
            case "export":{var p=exportParams.Where(x=>ExportFormat=="onnx"||x.Key is "imgsz" or "batch" or "dynamic").ToDictionary();p["quantize"]=int.Parse(Precision);p["device"]=ExportFormat=="engine"||Precision=="16"?"0":"cpu";await Start("export",new(){["model"]=SelectedModel,["format"]=ExportFormat,["params"]=p});break;}
            case "video-start":
                if(Busy){if(taskKind!="tracking"||VideoState is "waiting" or "starting")return;if(VideoState=="paused"){if(!await ResolveCandidate())return;if(GetNextId()>32)throw new InvalidOperationException("最多 32 个终身目标 ID");waitingAction="commit";await bridge.Call("task.control",new{project=Project,control=new{action="commit",pause_token=pauseToken,frame=Frame,targets=GetBoxes().Select(b=>new{id=b.TargetId,cls=b.ClassId,object_id=b.ObjectId,box=new[]{b.X1,b.Y1,b.X2,b.Y2},polygons=b.Polygons,holes=b.Holes}),next_id=GetNextId()}});}else{waitingAction="pause";await bridge.Call("task.control",new{project=Project,control=new{action="pause"}});}VideoState="waiting";}
                else{if(!await Save())return;var video=videoPath??throw new InvalidOperationException("请先选择视频");if(GetBoxes().Count==0){Go(PageAnnotation);Status="请先在当前帧画出目标，然后点“启动追踪”";break;}VideoState="starting";await Start("tracking",new(){["video"]=video,["frame_step"]=FrameStep,["targets"]=GetBoxes().Select(b=>new{id=b.TargetId,cls=b.ClassId,object_id=b.ObjectId,box=new[]{b.X1,b.Y1,b.X2,b.Y2},polygons=b.Polygons,holes=b.Holes}).ToArray(),["next_id"]=GetNextId(),["start_frame"]=Frame,["model"]=SelectedSam,["imgsz"]=SamSize,["device"]=Device});}break;
            case "video-finish-review":
                if(!Busy||taskKind!="tracking")return;
                if(VideoState is "waiting" or "starting")return;
                if(VideoState!="paused"){waitingAction="pause";await bridge.Call("task.control",new{project=Project,control=new{action="pause"}});VideoState="waiting";Status="已请求暂停；确认修正后再次选择“结束并复核”，点主按钮则继续追踪";break;}
                if(!await ResolveCandidate())return;
                waitingAction="commit";
                await bridge.Call("task.control",new{project=Project,control=new{action="finish_review",pause_token=pauseToken,frame=Frame,targets=GetBoxes().Select(b=>new{id=b.TargetId,cls=b.ClassId,object_id=b.ObjectId,box=new[]{b.X1,b.Y1,b.X2,b.Y2},polygons=b.Polygons,holes=b.Holes}),next_id=GetNextId()}});VideoState="waiting";break;
            case "extract-dialog":
            {
                var form=UserDialogs.Form("直接抽帧",new(){["帧步（5/10/15/20/30）"]=FrameStep.ToString()},explanation:"每 N 帧输出一张图片；完成后自动导入并进入待复审，人工画框继续标注。");
                if(form is null)break;
                if(!int.TryParse(form.Values.First(),out var step)||!FrameSteps.Contains(step))throw new InvalidOperationException("帧间隔只能选择 5、10、15、20 或 30");
                FrameStep=step;
                if(!await Save())break;
                if(videoPath is null)
                {
                    var vpaths=UserDialogs.Files("选择视频","视频|*.mp4;*.avi;*.mov;*.mkv;*.webm");
                    if(vpaths.Length==0)break;
                    await OpenVideo(vpaths[0]);
                    if(videoPath is null)break;
                }
                VideoState="starting";
                await Start("extract",new(){["video"]=videoPath,["frame_step"]=FrameStep});
                break;
            }
            case "restore-tracking":{if(!await Save())return;var run=UserDialogs.Folder("恢复当前项目的跟踪或抽帧任务");if(run is null)break;starting=true;Busy=true;try{var t=await bridge.Call("task.restore",new{project=Project,run});ActiveRun=run;taskKind=Text(t,"kind","tracking");taskSucceeded=false;firstProblem=null;trackingSession=Text(t,"session");videoPath=Text(t,"video");videoSession=trackingSession;Frame=-1;VideoState="starting";Go(PageAnnotation);}catch{Busy=false;earlyEvents.Clear();throw;}finally{starting=false;}foreach(var e in earlyEvents.ToArray())OnEvent(e);earlyEvents.Clear();break;}
            case "import-run":{var run=UserDialogs.Folder("导入抽帧或追踪结果，进入复审");if(run is not null)await Start("import_video",new(){["source_run"]=run});break;}
            case "import-current-run":await Start("import_video",new(){["source_run"]=ActiveRun});break;
            case "stop":await bridge.Call("task.cancel",new{force=false});Status="已请求停止，等待后台保存输出";break;
            case "force-stop":if(UserDialogs.Confirm("强制结束任务及其子进程？"))await bridge.Call("task.cancel",new{force=true});break;
            case "output":OpenFolder(ActiveRun);break;
            case "project-folder":OpenFolder(Project);break;
            case "settings-save":await bridge.Call("settings.save",new{settings=new{brand=Brand,logo=LogoPath,sam_imgsz=SamSize},preferences=new{acrylic=Acrylic,show_home=ShowHomeAtStartup}});MaterialChanged?.Invoke();Status="设置已保存";break;
            case "logo":LogoPath=UserDialogs.Files("选择应用图标","图片|*.png;*.jpg;*.ico").FirstOrDefault()??LogoPath;break;
            case "restart":if(Busy)throw new InvalidOperationException("请先停止当前任务");bridge.Dispose();bridge.Start();if(Project.Length>0)await bridge.Call("project.open",new{path=Project});Status="后端已重启；可以重试保存";break;
            default:if(action is not null)CanvasAction?.Invoke(action);break;
        }
    });
    public async Task Import(string[] paths)
    {
        if(!await Save())return;var result=await bridge.Call("images.import",new{project=Project,paths});ApplySnapshot(result.GetProperty("snapshot"));var names=result.GetProperty("names");
        await CompleteImport(names.EnumerateArray().Select(n=>n.GetString()!).ToArray());
        var report=result.GetProperty("report");var failures=report.GetProperty("failures");
        Status=$"已导入 {names.GetArrayLength()} 张 · 重复 {Number(report,"duplicates")} 张 · 失败 {failures.GetArrayLength()} 张";
        foreach(var failure in failures.EnumerateArray())AppendLog("导入失败："+Text(failure,"path")+" · "+Text(failure,"reason"));
    }
    public async Task Trash(string[] names)
    {
        if(names.Length==0||!UserDialogs.Confirm($"将 {names.Length} 张图片与标签移入项目回收目录？"))return;
        if(!await Save())return;await bridge.Call("images.trash",new{project=Project,names});if(names.Contains(CurrentName)){CurrentName="";Dirty=false;CanvasAction?.Invoke("clear-document");}await Refresh();
    }
    public async Task Transfer(string[] names,bool move)
    {
        if(!await Save())return;var destination=UserDialogs.Folder("选择目标项目，同步复制图片和标签");if(destination is null)return;
        await bridge.Call("images.transfer",new{project=Project,names,destination,move});if(move&&names.Contains(CurrentName)){CurrentName="";Dirty=false;CanvasAction?.Invoke("clear-document");}await Refresh();
    }
    public void ShowExperiment(int index)
    {
        if(index<0||index>=experiments.Count)return;var e=experiments[index];ResultJson=JsonSerializer.Serialize(e,new JsonSerializerOptions{WriteIndented=true});CurvePath=Path.Combine(e["output"].ToString()!,"results.png");
    }
    public void CompareExperiments(int[] indices)
    {
        var records=indices.Select(i=>experiments[i]).ToList();if(records.Count<2){Status="请选择至少两个实验";return;}
        var text=JsonSerializer.Serialize(records,new JsonSerializerOptions{WriteIndented=true});UserDialogs.Form("实验对比",new(){["参数与指标"]=text},true);
    }
    Dictionary<string,object> TrainParams(){var p=new Dictionary<string,object>(advanced);foreach(var a in augments)p[a.Key]=a.Value;p["epochs"]=Epochs;p["batch"]=Batch;p["lr0"]=LearningRate;p["imgsz"]=Imgsz;p["device"]=Device;return p;}
    string? LatestCheckpoint()
    {
        var runs=Path.Combine(Project,"runs");
        if(!Directory.Exists(runs))return null;
        foreach(var run in Directory.EnumerateDirectories(runs,"train_*").OrderByDescending(x=>x,StringComparer.Ordinal))
        {
            var last=Path.Combine(run,"train","weights","last.pt");
            if(File.Exists(last))return last;
        }
        return null;
    }
    static void OpenFolder(string path){if(Directory.Exists(path))Process.Start(new ProcessStartInfo("explorer.exe"){ArgumentList={path},UseShellExecute=true});}
    static void Fill(ObservableCollection<string> collection,JsonElement a){collection.Clear();foreach(var x in a.EnumerateArray())collection.Add(x.GetString()!);}
    public static string Text(JsonElement e,string key,string fallback="")=>e.ValueKind==JsonValueKind.Object&&e.TryGetProperty(key,out var v)&&v.ValueKind is not JsonValueKind.Null?v.ToString():fallback;
    public static int Number(JsonElement e,string key,int fallback=0)=>e.ValueKind==JsonValueKind.Object&&e.TryGetProperty(key,out var v)&&v.ValueKind==JsonValueKind.Number?v.GetInt32():fallback;
    static Dictionary<string,object> Dictionary(JsonElement e)=>e.EnumerateObject().ToDictionary(p=>p.Name,p=>(object)p.Value.Clone());
    public void Dispose()=>bridge.Dispose();
}
