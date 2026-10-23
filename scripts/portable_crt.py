"""Extract Microsoft's signed redistributable to app-local DLLs, without installing it."""
import hashlib
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET


def enable_utf8_manifest(path):
    """Keep the interpreter unchanged; enable Windows UTF-8 filename APIs for native deps."""
    import ctypes
    from ctypes import wintypes as W
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LoadLibraryExW.argtypes=[W.LPCWSTR,W.HANDLE,W.DWORD];kernel.LoadLibraryExW.restype=W.HMODULE
    kernel.FindResourceW.argtypes=[W.HMODULE,ctypes.c_void_p,ctypes.c_void_p];kernel.FindResourceW.restype=W.HANDLE
    kernel.LoadResource.argtypes=[W.HMODULE,W.HANDLE];kernel.LoadResource.restype=W.HANDLE
    kernel.LockResource.argtypes=[W.HANDLE];kernel.LockResource.restype=ctypes.c_void_p
    kernel.SizeofResource.argtypes=[W.HMODULE,W.HANDLE];kernel.SizeofResource.restype=W.DWORD
    kernel.FreeLibrary.argtypes=[W.HMODULE]
    module=kernel.LoadLibraryExW(str(path),None,0x22)
    if not module:raise ctypes.WinError(ctypes.get_last_error())
    try:
        resource=kernel.FindResourceW(module,1,24)
        if not resource:raise RuntimeError('Python 启动器缺少应用清单')
        raw=ctypes.string_at(kernel.LockResource(kernel.LoadResource(module,resource)),kernel.SizeofResource(module,resource))
        document=ET.fromstring(raw)
        application=document.find('{urn:schemas-microsoft-com:asm.v3}application')
        if application is None:application=ET.SubElement(document,'{urn:schemas-microsoft-com:asm.v3}application')
        settings=application.find('{urn:schemas-microsoft-com:asm.v3}windowsSettings')
        if settings is None:settings=ET.SubElement(application,'{urn:schemas-microsoft-com:asm.v3}windowsSettings')
        tag='{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage'
        active=settings.find(tag)
        if active is None:active=ET.SubElement(settings,tag)
        active.text='UTF-8'
        updated=ET.tostring(document,encoding='utf-8',xml_declaration=True)
        languages=[]
        callback_type=ctypes.WINFUNCTYPE(W.BOOL,W.HMODULE,ctypes.c_void_p,ctypes.c_void_p,W.WORD,ctypes.c_ssize_t)
        callback=callback_type(lambda h,t,n,language,param:languages.append(language) or True)
        kernel.EnumResourceLanguagesW.argtypes=[W.HMODULE,ctypes.c_void_p,ctypes.c_void_p,callback_type,ctypes.c_ssize_t]
        kernel.EnumResourceLanguagesW(module,24,1,callback,0)
    finally:kernel.FreeLibrary(module)
    kernel.BeginUpdateResourceW.argtypes=[W.LPCWSTR,W.BOOL];kernel.BeginUpdateResourceW.restype=W.HANDLE
    kernel.UpdateResourceW.argtypes=[W.HANDLE,ctypes.c_void_p,ctypes.c_void_p,W.WORD,ctypes.c_void_p,W.DWORD]
    kernel.EndUpdateResourceW.argtypes=[W.HANDLE,W.BOOL]
    handle=kernel.BeginUpdateResourceW(str(path),False)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer=ctypes.create_string_buffer(updated)
        for language in languages or [1033]:
            if not kernel.UpdateResourceW(handle,24,1,language,buffer,len(updated)):raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        kernel.EndUpdateResourceW(handle,True);raise
    if not kernel.EndUpdateResourceW(handle,False):raise ctypes.WinError(ctypes.get_last_error())


def install_local(archive,work,target):
    work.mkdir(parents=True,exist_ok=True)
    data=archive.read_bytes();offset=0;dlls={};licenses=[]
    while True:
        offset=data.find(b'MSCF',offset)
        if offset<0:break
        size=struct.unpack_from('<I',data,offset+8)[0]
        if 30<size<=len(data)-offset:
            cabinet=work/f'{offset}.cab';cabinet.write_bytes(data[offset:offset+size])
            folder=work/str(offset);folder.mkdir(exist_ok=True)
            subprocess.run(['expand.exe','-F:*',str(cabinet),str(folder)],check=True,capture_output=True)
            for path in folder.iterdir():
                if path.name=='0':
                    manifest=ET.fromstring(path.read_text(encoding='utf-8-sig'))
                    for payload in manifest.iter():
                        if payload.get('FilePath')=='license.rtf':licenses.append(folder/payload.get('SourcePath'))
                if path.is_file() and path.read_bytes()[:4]==b'MSCF':
                    extracted=folder/(path.name+'-files');extracted.mkdir(exist_ok=True)
                    subprocess.run(['expand.exe','-F:*',str(path),str(extracted)],check=True,capture_output=True)
                    for file in extracted.glob('*.dll_amd64'):
                        name=file.name.removesuffix('_amd64')
                        if not name.lower().startswith('mfc'):dlls[name]=file
        offset+=4
    if 'msvcp140.dll' not in dlls:raise ValueError('Microsoft CRT 解包不完整')
    receipt=[]
    for name,source in sorted(dlls.items()):
        for role in ('core','asr','document'):shutil.copy2(source,target/'runtime'/role/name)
        receipt.append({'file':name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    for source in licenses:shutil.copy2(source,target/'licenses/Microsoft-VC-LICENSE.rtf')
    return receipt
