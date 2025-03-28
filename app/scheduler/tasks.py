"""
设备任务处理模块

该模块负责处理设备相关的任务，主要分为两类：
1. 立即执行任务 - 设备上传数据后立即执行
2. 定时执行任务 - 按计划时间执行的任务

主要功能：
- 异步执行各类设备任务
- 结构化管理不同类型的任务
- 处理任务执行过程中的异常
- 记录任务执行日志
"""

import logging
import os
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Callable, Coroutine, Optional, List

from app.device.adb import adb, ADBException
from app.core.config import Settings, UPLOAD_DIR
from app.device.automation import AndroidAutomation

logger = logging.getLogger(__name__)

# 立即执行任务
# ===============================================

async def send_images_to_device(device_name: str, upload_time: int):
    """
    将上传的图片通过ADB发送到设备
    
    Args:
        device_name: 设备名称
        upload_time: 数据上传时间戳
    """
    try:
        # 记录详细诊断信息
        logger.info(f"===== 开始发送图片任务 - 设备名: {device_name} =====")
        
        # 获取设备映射信息用于诊断
        logger.info(f"设备映射配置: {Settings.DEVICE_MAPPING}")
        logger.info(f"设备配置: {Settings.DEVICE_CONFIG[device_name]}")
        
        # 1. 检查设备连接状态
        logger.info(f"正在检查设备 {device_name} 的连接状态...")
        try:
            # 先直接获取所有已连接设备
            connected_devices = await adb.get_connected_devices_async()
            logger.info(f"当前已连接的设备ID列表: {connected_devices}")
            
            # 尝试获取设备ID
            device_id = adb._get_device_id(device_name)
            logger.info(f"设备 {device_name} 的设备ID: {device_id}")
            
            # 检查设备连接状态
            is_connected = await adb.is_device_connected_async(device_name)
            logger.info(f"设备 {device_name} 连接状态: {'已连接' if is_connected else '未连接'}")
            
            if not is_connected:
                # 如果未连接，尝试连接
                logger.info(f"设备 {device_name} 未连接，正在尝试连接...")
                await adb.connect_device_async(device_id)
                
                # 再次检查连接状态
                is_connected = await adb.is_device_connected_async(device_name)
                logger.info(f"连接尝试后的状态: {'已连接' if is_connected else '仍未连接'}")
                
                if not is_connected:
                    logger.error(f"设备 {device_name} 无法连接，终止任务")
                    return False
        except Exception as e:
            logger.error(f"检查设备连接状态时出错: {str(e)}")
            return False
        
        # 2. 获取设备配置和存储路径
        device_config = Settings.DEVICE_CONFIG[device_name]
        device_storage_path = device_config['storage_path']
        logger.info(f"设备 {device_name} 的存储路径: {device_storage_path}")
        
        # 3. 创建格式化的时间子目录
        time_dir = datetime.fromtimestamp(upload_time).strftime("%Y%m%d%H%M%S")
        local_dir = UPLOAD_DIR / device_name / time_dir / "imgs"
        remote_dir = f"{device_storage_path.rstrip('/')}/{time_dir}"
        
        logger.info(f"本地图片目录: {local_dir}")
        logger.info(f"设备目标目录: {remote_dir}")
        
        # 4. 在设备上创建目标目录
        try:
            mkdir_cmd = ["shell", f"mkdir -p {remote_dir}"]
            logger.info(f"执行创建目录命令: adb -s {device_id} {' '.join(mkdir_cmd)}")
            
            await adb.execute_device_command_async(
                device_name,
                mkdir_cmd
            )
            logger.info(f"在设备 {device_name} 上创建目录成功: {remote_dir}")
        except ADBException as e:
            logger.error(f"在设备 {device_name} 上创建目录失败: {str(e)}")
            return False
        
        # 5. 获取本地图片文件列表
        if not local_dir.exists():
            logger.warning(f"本地图片目录不存在: {local_dir}")
            return False
            
        image_files = list(local_dir.glob("*.*"))
        logger.info(f"找到 {len(image_files)} 个图片文件需要发送")
        
        if not image_files:
            logger.warning(f"没有找到图片文件在: {local_dir}")
            return False
            
        # 6. 逐个推送图片到设备
        successful_transfers = 0
        for img_path in image_files:
            try:
                remote_path = f"{remote_dir}/{img_path.name}"
                push_cmd = ["push", str(img_path), remote_path]
                logger.info(f"执行推送命令: adb -s {device_id} {' '.join(push_cmd)}")
                
                await adb.execute_device_command_async(
                    device_name,
                    push_cmd
                )
                logger.info(f"成功推送图片到设备 {device_name}: {remote_path}")
                successful_transfers += 1
            except ADBException as e:
                logger.error(f"推送图片 {img_path.name} 到设备 {device_name} 失败: {str(e)}")
        
        logger.info(f"推送完成: {successful_transfers}/{len(image_files)} 文件成功发送到设备 {device_name}")
        logger.info(f"===== 图片发送任务结束 - 设备名: {device_name} =====")
        return successful_transfers > 0
    except Exception as e:
        logger.error(f"发送图片到设备 {device_name} 时发生错误: {str(e)}", exc_info=True)
        return False

async def send_upload_notification(device_name: str, upload_time: int, success: bool = True):
    """
    发送上传完成通知
    
    Args:
        device_name: 设备名称
        upload_time: 数据上传时间戳
        success: 图片传输是否成功
    """
    try:
        logger.info(f"===== 开始发送通知任务 - 设备名: {device_name} =====")
        
        # 检查设备连接状态
        is_connected = await adb.is_device_connected_async(device_name)
        logger.info(f"发送通知前设备 {device_name} 连接状态: {'已连接' if is_connected else '未连接'}")
        
        if not is_connected:
            logger.warning(f"设备 {device_name} 未连接，无法发送通知")
            return
        
        # 获取设备配置
        device_config = Settings.DEVICE_CONFIG[device_name]
        device_id = adb._get_device_id(device_name)
        
        # 使用设备配置中的存储路径
        storage_path = device_config['storage_path']
        time_dir = datetime.fromtimestamp(upload_time).strftime("%Y%m%d%H%M%S")
        scan_path = f"{storage_path.rstrip('/')}/{time_dir}"
        
        notification_cmd = [
            "shell", 
            f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{scan_path}"
        ]
        
        logger.info(f"执行通知命令: adb -s {device_id} {' '.join(notification_cmd)}")
        
        try:
            await adb.execute_device_command_async(device_name, notification_cmd)
            logger.info(f"已发送媒体扫描通知到设备 {device_name}")
        except ADBException as e:
            logger.error(f"发送通知到设备 {device_name} 失败: {str(e)}")
            
        logger.info(f"===== 发送通知任务结束 - 设备名: {device_name} =====")
    except Exception as e:
        logger.error(f"处理设备通知时发生错误: {str(e)}", exc_info=True)

# 立即任务调度器
async def execute_immediate_tasks(device_name: str, upload_time: int):
    """
    执行所有立即任务的调度器
    
    集中调度所有需要立即执行的任务，统一管理异常处理和日志记录。
    
    Args:
        device_name: 设备名称
        upload_time: 数据上传时间戳
    """
    logger.info(f"=========================================")
    logger.info(f"开始执行立即任务 - 设备: {device_name}, 时间: {datetime.fromtimestamp(upload_time)}")
    logger.info(f"=========================================")
    
    try:
        # 1. 执行图片发送任务
        success = await send_images_to_device(device_name, upload_time)
        
        # 2. 发送操作完成通知
        await send_upload_notification(device_name, upload_time, success)
        
        logger.info(f"=========================================")
        logger.info(f"所有立即任务完成 - 设备: {device_name}")
        logger.info(f"=========================================")
    except Exception as e:
        logger.error(f"立即任务执行过程中出现未处理异常: {str(e)}", exc_info=True)

# 定时执行任务
# ===============================================

async def perform_data_cleanup(device_name: str, task_time: int) -> bool:
    """
    执行数据清理任务
    
    Args:
        device_name: 设备名称
        task_time: 计划执行时间戳
        
    Returns:
        bool: 清理是否成功
    """
    try:
        logger.info(f"执行数据清理 - 设备: {device_name}, 计划时间: {datetime.fromtimestamp(task_time)}")
        # TODO: 实现数据清理逻辑
        return True  # 暂时返回 True，因为目前没有实际的清理逻辑
    except Exception as e:
        logger.error(f"数据清理失败: {str(e)}")
        return False

async def perform_content_automation(device_name: str, task_time: int):
    """
    执行内容自动化发布任务
    
    Args:
        device_name: 设备名称
        task_time: 计划执行时间戳
    """
    try:
        logger.info(f"开始执行内容自动化任务 - 设备: {device_name}")
        
        # 检查设备配置
        if device_name not in Settings.DEVICE_CONFIG:
            logger.error(f"设备 {device_name} 配置不存在")
            return False
            
        # 获取要发布的内容
        title, content = await get_content_from_file(device_name, task_time)
        logger.info(f"准备发布内容 - 标题: {title if title else '[无标题]'}, 正文长度: {len(content) if content else 0}")
            
        # 初始化自动化实例
        automation = AndroidAutomation(device_name)
        
        # 连接设备
        if not automation.connect_device():
            logger.error(f"设备 {device_name} 连接失败")
            return False
            
        # 构建图片路径
        time_dir = datetime.fromtimestamp(task_time).strftime("%Y%m%d%H%M%S")
        local_dir = UPLOAD_DIR / device_name / time_dir / "imgs"
        
        # 检查目录是否存在
        if not local_dir.exists():
            logger.error(f"图片目录不存在: {local_dir}")
            return False
            
        image_paths = [str(p) for p in local_dir.glob("*.*")]
        
        if not image_paths:
            logger.error(f"未找到需要发布的图片: {local_dir}")
            return False
            
        # 执行发布操作
        success, status = automation.post_content(title, content, image_paths)
        
        if success:
            logger.info(f"内容发布成功 - 设备: {device_name}")
        else:
            logger.error(f"内容发布失败 - 设备: {device_name}, 状态: {status}")
            
        return success
        
    except Exception as e:
        logger.error(f"执行内容自动化任务失败: {str(e)}", exc_info=True)
        return False

async def get_content_from_file(device_name: str, task_time: int) -> tuple[Optional[str], Optional[str]]:
    """
    从上传目录中获取内容文件并解析标题和内容
    
    Args:
        device_name: 设备名称
        task_time: 任务时间戳
        
    Returns:
        tuple: (标题, 正文内容)
    """
    try:
        time_dir = datetime.fromtimestamp(task_time).strftime("%Y%m%d%H%M%S")
        content_dir = UPLOAD_DIR / device_name / time_dir
        
        # 读取content.txt文件
        content_file = content_dir / "content.txt"
        if not content_file.exists():
            logger.warning(f"内容文件不存在: {content_file}")
            return None, None
            
        # 读取文件内容
        file_content = content_file.read_text(encoding='utf-8').strip()
        
        # 解析标题和内容
        title = None
        content = None
        
        # 按行分割
        lines = file_content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('Title:'):
                title = line.replace('Title:', '').strip()
            elif line.startswith('Content:'):
                # 获取Content:后面的所有内容
                content_start = file_content.index('Content:') + 8
                content = file_content[content_start:].strip()
                break
        
        logger.debug(f"解析到标题: {title}")
        logger.debug(f"解析到正文，长度: {len(content) if content else 0}")
        
        return title, content
        
    except Exception as e:
        logger.error(f"读取或解析内容文件失败: {str(e)}")
        return None, None

# 定时任务调度器
async def execute_scheduled_tasks(device_name: str, task_time: int, task_type: Optional[str] = None):
    """
    执行定时任务的调度器
    
    Args:
        device_name: 设备名称
        task_time: 计划执行的时间戳
        task_type: 可选的任务类型，为None时执行所有定时任务
        
    Returns:
        bool: 任务执行是否成功
    """
    logger.info(f"开始执行定时任务 - 设备: {device_name}, 类型: {task_type or '全部'}")
    
    try:
        success = True
        
        if task_type is None or task_type == "cleanup":
            cleanup_success = await perform_data_cleanup(device_name, task_time)
            if cleanup_success is not None:  # 只有在有明确返回值时才更新 success
                success = success and cleanup_success
            
        if task_type is None or task_type == "automation":
            automation_success = await perform_content_automation(device_name, task_time)
            if automation_success is not None:  # 只有在有明确返回值时才更新 success
                success = success and automation_success
            
        logger.info(f"定时任务完成 - 设备: {device_name}, 类型: {task_type or '全部'}, 结果: {'成功' if success else '失败'}")
        return success
        
    except Exception as e:
        logger.error(f"定时任务执行过程中出现未处理异常: {str(e)}")
        return False