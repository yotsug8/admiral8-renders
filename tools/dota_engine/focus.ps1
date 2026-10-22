# Вывести окно «Dota 2» вперёд (SW_RESTORE: окно само сворачивается, когда теряет фокус) и растянуть до 1080×1920 физических пикселей (864×1536 логических при масштабе 125 %).
# Дота рисует кадры, только когда окно впереди; после этого ещё нужен щелчок по окну (computer-use).
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class A8Win { public delegate bool P(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(P p, IntPtr l);
 [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h,IntPtr a,int x,int y,int w,int ht,uint f);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
 public static IntPtr Find(uint pid,string title){ IntPtr f=IntPtr.Zero; EnumWindows((h,l)=>{uint p; GetWindowThreadProcessId(h,out p); var s=new StringBuilder(256); GetWindowText(h,s,256); if(p==pid && IsWindowVisible(h) && s.ToString()==title){f=h; return false;} return true;},IntPtr.Zero); return f;}
}
"@
$p = (Get-Process dota2 | Sort-Object StartTime -Descending)[0].Id
$h = [A8Win]::Find([uint32]$p, "Dota 2")
 [A8Win]::ShowWindow($h, 9) | Out-Null
[A8Win]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, 864, 1536, 0x0040) | Out-Null
# Windows не отдаёт передний план фоновому процессу, если пользователь недавно нажимал клавиши;
# нажатие Alt снимает этот замок (стандартный обход), после чего SetForegroundWindow срабатывает.
for ($i = 0; $i -lt 5 -and [A8Win]::GetForegroundWindow() -ne $h; $i++) {
  [A8Win]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [A8Win]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
  [A8Win]::SetForegroundWindow($h) | Out-Null
  Start-Sleep -Milliseconds 300
}
"hwnd=$h fg=$([A8Win]::GetForegroundWindow() -eq $h)"
