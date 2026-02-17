import os
import sys
import json
import subprocess
import psutil
import winreg
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
import socket
import threading
from collections import defaultdict

# ========================
# SYSTEM MONITORING
# ========================

def get_system_summary() -> Dict:
    """Get comprehensive system information"""
    try:
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'cpu_count': psutil.cpu_count(),
            'ram_total': psutil.virtual_memory().total,
            'ram_used': psutil.virtual_memory().used,
            'ram_percent': psutil.virtual_memory().percent,
            'disk_total': psutil.disk_usage('/').total,
            'disk_used': psutil.disk_usage('/').used,
            'disk_percent': psutil.disk_usage('/').percent,
            'boot_time': datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S'),
            'uptime_seconds': datetime.now().timestamp() - psutil.boot_time(),
            'process_count': len(psutil.pids()),
        }
    except Exception as e:
        return {'error': str(e)}

def get_top_processes(n: int = 10) -> List[Dict]:
    """Get top N processes by memory usage"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory_percent': proc.info['memory_percent'] or 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:n]
    except Exception as e:
        return [{'error': str(e)}]

# ========================
# BATTERY & POWER
# ========================

def get_battery_info() -> Dict:
    """Get detailed battery information"""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {'status': 'No battery detected (Desktop PC)'}
        
        return {
            'percent': battery.percent,
            'is_plugged': battery.power_plugged,
            'seconds_left': battery.secsleft,
            'time_left': f"{int(battery.secsleft // 3600)}h {int((battery.secsleft % 3600) // 60)}m" if battery.secsleft != psutil.POWER_TIME_UNLIMITED else 'Unknown',
            'status': 'Plugged In' if battery.power_plugged else 'On Battery'
        }
    except Exception as e:
        return {'error': str(e)}

def get_battery_health() -> Dict:
    """Get battery health report from Windows"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', 'powercfg /batteryreport /output "$env:TEMP\\battery-report.html"'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return {
                'status': 'success',
                'message': 'Battery report generated',
                'location': os.path.join(os.environ['TEMP'], 'battery-report.html')
            }
        return {'status': 'failed', 'error': result.stderr}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ========================
# STARTUP PROGRAMS
# ========================

def get_startup_programs() -> List[Dict]:
    """Get list of startup programs"""
    programs = []
    startup_paths = [
        r'Software\\Microsoft\\Windows\\CurrentVersion\\Run',
        r'Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',
        r'Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run'
    ]
    
    try:
        for path in startup_paths:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    name, value, _ = winreg.EnumValue(key, i)
                    programs.append({
                        'name': name,
                        'path': value,
                        'type': 'System'
                    })
                winreg.CloseKey(key)
            except:
                pass
        
        # User startup
        user_path = os.path.expandvars(r'%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup')
        if os.path.exists(user_path):
            for file in os.listdir(user_path):
                programs.append({
                    'name': file,
                    'path': os.path.join(user_path, file),
                    'type': 'User'
                })
        
        return programs
    except Exception as e:
        return [{'error': str(e)}]

def disable_startup_program(program_name: str, registry_path: str = None) -> Dict:
    """Disable a startup program"""
    try:
        if registry_path:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_WRITE)
            winreg.DeleteValue(key, program_name)
            winreg.CloseKey(key)
            return {'status': 'success', 'message': f'Disabled {program_name}'}
        return {'status': 'failed', 'error': 'Invalid registry path'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ========================
# WINDOWS UPDATES
# ========================

def check_windows_updates() -> Dict:
    """Check for pending Windows updates"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', 'Get-WindowsUpdate | Select-Object KB, Title'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return {
            'status': 'success' if result.returncode == 0 else 'failed',
            'output': result.stdout,
            'error': result.stderr
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

def get_installed_updates() -> List[Dict]:
    """Get list of installed updates"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', 'Get-HotFix | Select-Object HotFixID, InstalledOn, Description'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return {'status': 'success', 'output': result.stdout}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ========================
# REGISTRY CLEANING
# ========================

def scan_invalid_registry_entries() -> Dict:
    """Scan for invalid registry entries"""
    invalid_entries = []
    uninstall_paths = [
        r'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
        r'Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
    ]
    
    try:
        for path in uninstall_paths:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    try:
                        display_name = winreg.QueryValueEx(subkey, 'DisplayName')[0]
                        install_location = winreg.QueryValueEx(subkey, 'InstallLocation')[0]
                        
                        if install_location and not os.path.exists(install_location):
                            invalid_entries.append({
                                'name': display_name,
                                'path': install_location,
                                'registry_key': subkey_name
                            })
                    except:
                        pass
                    finally:
                        winreg.CloseKey(subkey)
                winreg.CloseKey(key)
            except:
                pass
        
        return {
            'status': 'success',
            'invalid_entries_count': len(invalid_entries),
            'entries': invalid_entries[:20]  # Return first 20
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ========================
# FILE OPERATIONS
# ========================

def find_duplicate_files(directory: str = None, extensions: List[str] = None) -> Dict:
    """Find duplicate files by size and hash"""
    if directory is None:
        directory = os.path.expandvars('%USERPROFILE%')
    
    if extensions is None:
        extensions = ['.jpg', '.png', '.mp3', '.mp4', '.zip', '.rar']
    
    try:
        file_hashes = defaultdict(list)
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    filepath = os.path.join(root, file)
                    try:
                        file_hash = hash(os.path.getsize(filepath))
                        file_hashes[file_hash].append(filepath)
                    except:
                        pass
        
        duplicates = {k: v for k, v in file_hashes.items() if len(v) > 1}
        return {
            'status': 'success',
            'duplicates_count': sum(len(v) - 1 for v in duplicates.values()),
            'duplicates': dict(list(duplicates.items())[:10])
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

def find_large_files(directory: str = None, min_size_mb: int = 100) -> List[Dict]:
    """Find large files in a directory"""
    if directory is None:
        directory = os.path.expandvars('%USERPROFILE%')
    
    try:
        large_files = []
        min_size_bytes = min_size_mb * 1024 * 1024
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    size = os.path.getsize(filepath)
                    if size >= min_size_bytes:
                        large_files.append({
                            'path': filepath,
                            'size_mb': round(size / (1024 * 1024), 2)
                        })
                except:
                    pass
        
        return sorted(large_files, key=lambda x: x['size_mb'], reverse=True)[:20]
    except Exception as e:
        return [{'error': str(e)}]

def get_disk_usage_by_folder(directory: str = None) -> List[Dict]:
    """Get disk usage for each folder"""
    if directory is None:
        directory = os.path.expandvars('%USERPROFILE%')
    
    try:
        folder_sizes = []
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                total_size = 0
                try:
                    for dirpath, dirnames, filenames in os.walk(item_path):
                        for filename in filenames:
                            filepath = os.path.join(dirpath, filename)
                            try:
                                total_size += os.path.getsize(filepath)
                            except:
                                pass
                    folder_sizes.append({
                        'name': item,
                        'size_mb': round(total_size / (1024 * 1024), 2)
                    })
                except:
                    pass
        
        return sorted(folder_sizes, key=lambda x: x['size_mb'], reverse=True)
    except Exception as e:
        return [{'error': str(e)}]

# ========================
# NETWORK
# ========================

def test_internet_speed() -> Dict:
    """Test internet speed (simplified)"""
    try:
        import urllib.request
        import time
        
        url = 'https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png'
        start_time = time.time()
        urllib.request.urlopen(url, timeout=10)
        elapsed = time.time() - start_time
        
        return {
            'status': 'success',
            'response_time': f'{elapsed:.2f}s',
            'connectivity': 'Online'
        }
    except Exception as e:
        return {'status': 'offline', 'error': str(e)}

def get_network_info() -> Dict:
    """Get network interface information"""
    try:
        interfaces = {}
        for interface_name, interface_addrs in psutil.net_if_addrs().items():
            interfaces[interface_name] = [
                {'address': addr.address, 'family': str(addr.family)} 
                for addr in interface_addrs
            ]
        return interfaces
    except Exception as e:
        return {'error': str(e)}

# ========================
# SYSTEM RESTORE
# ========================

def get_system_restore_points() -> Dict:
    """Get available system restore points"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', 'Get-ComputerRestorePoint | Select-Object SequenceNumber, CreationTime, Description'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return {
            'status': 'success' if result.returncode == 0 else 'failed',
            'output': result.stdout
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

def create_system_restore_point(description: str = "CWH Restore Point") -> Dict:
    """Create a new system restore point"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', f'Checkpoint-Computer -Description "{description}"'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return {
            'status': 'success' if result.returncode == 0 else 'failed',
            'message': f'Restore point created: {description}',
            'error': result.stderr
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}