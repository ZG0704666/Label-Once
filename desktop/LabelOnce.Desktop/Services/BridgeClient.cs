using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
namespace LabelOnce.Desktop.Services;

public sealed class BridgeClient : IDisposable
{
    Process? process;
    long next;
    readonly ConcurrentDictionary<string,TaskCompletionSource<JsonElement>> pending=new();
    readonly SemaphoreSlim writer=new(1,1);
    public event Action<JsonElement>? Event;
    public event Action<string>? Log;
    public event Action<string>? Faulted;
    public bool Alive => process is {HasExited:false};
    public void Start()
    {
        if(Alive)return;
        process?.Dispose();process=null;
        string root=AppContext.BaseDirectory;
        string backend=Environment.GetEnvironmentVariable("LABELONCE_BACKEND")??Path.Combine(root,"backend","backend.exe");
        var info=new ProcessStartInfo {UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
        if(File.Exists(backend)){info.FileName=backend;info.ArgumentList.Add("--bridge");info.WorkingDirectory=Path.GetDirectoryName(backend)!;}
        else
        {
            string? source=Environment.GetEnvironmentVariable("LABELONCE_SOURCE");
            for(var dir=new DirectoryInfo(root);source is null&&dir is not null;dir=dir.Parent)
                if(File.Exists(Path.Combine(dir.FullName,"backend_launch.py")))source=dir.FullName;
            if(source is null)throw new FileNotFoundException("未找到 backend/backend.exe。请运行 desktop/scripts/start.ps1 或使用完整发布目录。");
            string python=Environment.GetEnvironmentVariable("LABELONCE_PYTHON")??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),"anaconda3","envs","labelonce","python.exe");
            info.FileName=python;info.WorkingDirectory=source;info.ArgumentList.Add("-X");info.ArgumentList.Add("utf8");info.ArgumentList.Add("-m");info.ArgumentList.Add("studio.bridge");
        }
        info.Environment["PYTHONUTF8"]="1";info.Environment["YOLO_AUTOINSTALL"]="False";
        process=Process.Start(info)??throw new IOException("无法启动业务后端");
        _=Read(process);_=ReadLog(process);
    }
    async Task Read(Process proc)
    {
        try
        {
            while(await proc.StandardOutput.ReadLineAsync() is { } raw)
            {
                if(!ReferenceEquals(process,proc))return;
                // 协议容错：第三方库可能仍漏出日志行或 BOM 到 stdout。脏行只降级为日志忽略，绝不让整条桥崩溃。
                var line=raw.TrimStart('\uFEFF',' ','\t');
                if(line.Length==0)continue;
                JsonDocument doc;
                try{doc=JsonDocument.Parse(line);}
                catch(JsonException dirty){Fail(proc,"忽略无法解析的后端输出："+dirty.Message);continue;}
                using(doc)
                {
                    var message=doc.RootElement;
                    if(!message.TryGetProperty("version",out var versionEl)||versionEl.ValueKind!=System.Text.Json.JsonValueKind.Number||versionEl.GetInt32()!=1){Fail(proc,"忽略版本异常的后端输出，请更新后端");continue;}
                    if(message.TryGetProperty("event",out var evt)){var copy=evt.Clone();_=Application.Current.Dispatcher.BeginInvoke(()=>{if(ReferenceEquals(process,proc))Event?.Invoke(copy);});}
                    else if(message.TryGetProperty("id",out var id)&&pending.TryRemove(id.ToString(),out var completion))
                    {
                        if(message.TryGetProperty("error",out var error))completion.TrySetException(new IOException(error.TryGetProperty("message",out var msg)?msg.GetString():error.GetRawText()));
                        else completion.TrySetResult(message.GetProperty("result").Clone());
                    }
                }
            }
            throw new IOException("业务后端已退出；当前标注仍保留，请到 设置 → 诊断与恢复 → 重启后端 后重试。");
        }
        catch(Exception exc){if(!ReferenceEquals(process,proc))return;foreach(var pair in pending)if(pending.TryRemove(pair.Key,out var t))t.TrySetException(exc);_=Application.Current.Dispatcher.BeginInvoke(()=>{if(ReferenceEquals(process,proc)){Log?.Invoke(exc.Message);Faulted?.Invoke(exc.Message);}});}
    }
    void Fail(Process proc,string text){_=Application.Current.Dispatcher.BeginInvoke(()=>{if(ReferenceEquals(process,proc))Log?.Invoke(text);});}
    async Task ReadLog(Process proc)
    {
        try{while(await proc.StandardError.ReadLineAsync() is { } line){if(!ReferenceEquals(process,proc))return;_=Application.Current.Dispatcher.BeginInvoke(()=>Log?.Invoke(line));}}catch(ObjectDisposedException){}catch(IOException){}
    }
    public async Task<JsonElement> Call(string method, object? parameters=null)
    {
        if(!Alive)throw new IOException("业务后端未运行；请到 设置 → 诊断与恢复 → 重启后端");
        string id=Interlocked.Increment(ref next).ToString();
        var completion=new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);pending[id]=completion;
        try
        {
            await writer.WaitAsync();
            try{await process!.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new {version=1,id,method,@params=parameters??new {}}));await process.StandardInput.FlushAsync();}
            finally{writer.Release();}
            try{return await completion.Task.WaitAsync(TimeSpan.FromMinutes(30));}
            catch(TaskCanceledException){throw new IOException("后端响应超时（30 分钟未应答，后台可能仍在处理）；可稍后重试或到日志页查看进展。");}
        }
        finally{pending.TryRemove(id,out _);}
    }
    public void Dispose()
    {
        if(process is {HasExited:false}){process.StandardInput.Close();if(!process.WaitForExit(15000))process.Kill(true);}process?.Dispose();process=null;foreach(var pair in pending)if(pending.TryRemove(pair.Key,out var completion))completion.TrySetException(new IOException("后端连接已关闭，可重新保存"));
    }
}
