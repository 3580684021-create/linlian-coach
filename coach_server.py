#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邻练体育 - 教练端本地服务器
功能：
1. 提供教练端界面访问
2. 从飞书读取学生列表
3. 提交体测数据到飞书
4. 触发PDF报告生成
5. 视频AI识别（硅基流动API）
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import socket
import urllib.request
import urllib.parse
from urllib.parse import urlparse
from datetime import datetime
import base64
import requests
import os
import subprocess
import tempfile

# 配置信息（从环境变量读取，提供默认值用于本地开发）
import os

FEISHU_CONFIG = {
    'app_id': os.environ.get('FEISHU_APP_ID', 'cli_aa8943c2e9381cde'),
    'app_secret': os.environ.get('FEISHU_APP_SECRET', 'M6Nb3vLmsUPRkFD4xEoO8d18JZTa1N3k'),
    'base_token': os.environ.get('FEISHU_BASE_TOKEN', 'UTJobXJT1a85lDspZfecgPDXnCc'),
    'table_id': os.environ.get('FEISHU_TABLE_ID', 'tblPyAhmraamWM1u'),
    'booking_table_id': os.environ.get('FEISHU_BOOKING_TABLE_ID', 'tblPyAhmraamWM1u'),
    'test_table_id': os.environ.get('FEISHU_TEST_TABLE_ID', 'tblyY6kyPk3b62iL'),
}

HTML_DIR = os.environ.get('HTML_DIR', '/Users/mac/Desktop/workbuddy/Claw/邻练体测知识库/05_报告模板')

# 硅基流动 API 配置
SILICON_FLOW_CONFIG = {
    'api_key': os.environ.get('SILICON_FLOW_API_KEY', 'sk-ezmxsksbppopslxjglytlyhrkjxwopqrexgwqwykifiasirj'),
    'base_url': os.environ.get('SILICON_FLOW_BASE_URL', 'https://api.siliconflow.cn/v1'),
    'vision_model': os.environ.get('SILICON_FLOW_MODEL', 'Qwen/Qwen3-VL-8B-Instruct')
}

# 临时视频帧存储目录
TEMP_FRAME_DIR = "/tmp/linlian_video_frames"
os.makedirs(TEMP_FRAME_DIR, exist_ok=True)

# 获取飞书 access token
def get_feishu_token():
    """获取飞书访问令牌"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = {
        "app_id": FEISHU_CONFIG['app_id'],
        "app_secret": FEISHU_CONFIG['app_secret']
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        token = result.get('tenant_access_token')
        if token:
            print(f"✅ 获取飞书 token 成功")
            return token
        else:
            print(f"❌ 获取 token 失败: {result}")
            return None
    except Exception as e:
        print(f"❌ 获取 token 失败: {e}")
        return None

# 读取学生列表
def get_students():
    """从飞书读取预约学生列表"""
    token = get_feishu_token()
    if not token:
        print("⚠️  无法获取 token，返回模拟数据")
        return get_mock_students()
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_CONFIG['base_token']}/tables/{FEISHU_CONFIG['table_id']}/records"
    req = urllib.request.Request(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('code') != 0:
            print(f"❌ 读取学生列表失败: {result.get('msg')}")
            return get_mock_students()
        
        records = result.get('data', {}).get('items', [])
        
        students = []
        for record in records:
            fields = record.get('fields', {})
            # 处理预约日期（飞书时间戳格式，转为 YYYY-MM-DD）
            appt_ts = fields.get('预约日期')
            appointment_date = ''
            if appt_ts:
                try:
                    import time
                    appointment_date = time.strftime('%Y-%m-%d', time.localtime(int(appt_ts) / 1000))
                except:
                    appointment_date = str(appt_ts)

            students.append({
                'record_id': record.get('record_id'),
                'name': fields.get('孩子姓名', fields.get('多行文本', '未知')),
                'gender': fields.get('性别', '男'),
                'age': fields.get('年龄', 7),
                'phone': fields.get('联系电话', ''),
                'appointment_date': appointment_date,
                'appointment_time': fields.get('预约时段', ''),
                'location': fields.get('预约地点', '人民街道党群服务中心'),
                'booking_no': fields.get('预约编号', ''),
                'status': fields.get('状态', '已预约')
            })
        
        print(f"✅ 从飞书读取到 {len(students)} 条学生数据")
        return students
    except Exception as e:
        print(f"❌ 读取学生列表失败: {e}")
        return get_mock_students()

def get_mock_students():
    """返回模拟学生数据"""
    return [
        {"record_id": "rec001", "name": "张小明", "gender": "男", "age": 8, "phone": "138****1234", "location": "人民街道党群", "booking_no": "20260517-001", "status": "已预约"},
        {"record_id": "rec002", "name": "李小红", "gender": "女", "age": 7, "phone": "139****5678", "location": "人民街道党群", "booking_no": "20260517-002", "status": "已到店"},
        {"record_id": "rec003", "name": "王小强", "gender": "男", "age": 9, "phone": "137****9012", "location": "人民街道党群", "booking_no": "20260517-003", "status": "已完成"}
    ]

# 提交预约
def submit_booking(booking_data):
    """提交预约信息到飞书"""
    token = get_feishu_token()
    if not token:
        print("⚠️  无法获取 token，模拟提交")
        print("📋 收到预约数据：")
        print(json.dumps(booking_data, ensure_ascii=False, indent=2))
        return {"success": True, "record_id": "mock_" + str(datetime.now().timestamp())}
    
    # 日期转时间戳（飞书日期字段需要毫秒级Unix时间戳）
    def to_timestamp(val):
        if not val:
            return None
        if isinstance(val, (int, float)):
            return int(val * 1000) if val < 10**12 else int(val)
        try:
            return int(datetime.fromisoformat(str(val).replace('Z', '+00:00')).timestamp() * 1000)
        except:
            return None
    
    # 构建飞书记录数据
    fields = {
        '孩子姓名': booking_data.get('child_name'),
        '性别': booking_data.get('gender'),
        '年龄': booking_data.get('age'),
        '身高(cm)': booking_data.get('height'),
        '体重(kg)': booking_data.get('weight'),
        '家长姓名': booking_data.get('parent_name'),
        '联系电话': booking_data.get('phone'),
        '微信号': booking_data.get('wechat', ''),
        '预约日期': to_timestamp(booking_data.get('appointment_date')),
        '预约时段': booking_data.get('appointment_time'),
        '预约地点': booking_data.get('location'),
        '备注信息': booking_data.get('remarks', ''),
        '提交时间': to_timestamp(booking_data.get('submit_time') or datetime.now().isoformat()),
        '状态': '已预约'
    }
    
    # 提交到飞书（学员档案表）
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_CONFIG['base_token']}/tables/{FEISHU_CONFIG['booking_table_id']}/records"
    
    payload = {
        "fields": fields
    }
    
    print(f"DEBUG submit_booking | booking_table={FEISHU_CONFIG['booking_table_id']}")
    print(f"DEBUG fields keys: {list(fields.keys())}")
    print(f"DEBUG 性别 value: {repr(fields.get('性别'))}")
    print(f"DEBUG 预约日期 value: {repr(fields.get('预约日期'))}")
    print(f"DEBUG payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('code') == 0:
            new_record_id = result['data']['record']['record_id']
            print(f"DEBUG submit SUCCESS: {new_record_id}")
            return {"success": True, "record_id": new_record_id}
        else:
            print(f"DEBUG Feishu ERROR: code={result.get('code')} msg={result.get('msg')}")
            print(f"❌ 预约提交失败: {result.get('msg')}")
            return {"success": False, "message": result.get('msg')}
    except Exception as e:
        print(f"❌ 预约提交失败: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}

# 获取体测数据
def get_test_data(record_id):
    """从飞书读取指定学生的体测数据"""
    token = get_feishu_token()
    if not token:
        print("⚠️  无法获取 token，返回模拟数据")
        return get_mock_test_data()
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_CONFIG['base_token']}/tables/{FEISHU_CONFIG['test_table_id']}/records?filter=CurrentValue.[学员姓名]={record_id}"
    req = urllib.request.Request(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('code') != 0:
            print(f"❌ 读取体测数据失败: {result.get('msg')}")
            return get_mock_test_data()
        
        records = result.get('data', {}).get('items', [])
        if not records:
            print(f"⚠️  未找到记录 {record_id} 的体测数据")
            return get_mock_test_data()
        
        fields = records[0].get('fields', {})
        
        data = {
            'height': fields.get('身高', ''),
            'weight': fields.get('体重', ''),
            'vital_capacity': fields.get('肺活量(ml)', ''),
            'standing_long_jump': fields.get('立定跳远(cm)', ''),
            'sit_and_reach': fields.get('体前屈(cm)', ''),
            'push_up': '',
            'plank': '',
            'risk_level': '低'
        }
        
        # 从备注中解析
        notes = fields.get('备注说明', '')
        if '跪姿俯卧撑' in notes:
            try:
                data['push_up'] = notes.split('跪姿俯卧撑: ')[1].split(' 次')[0]
            except:
                pass
        if '平板支撑' in notes:
            try:
                data['plank'] = notes.split('平板支撑: ')[1].split(' 秒')[0]
            except:
                pass
        
        print(f"✅ 读取到体测数据：{data}")
        return data
    except Exception as e:
        print(f"❌ 读取体测数据失败: {e}")
        return get_mock_test_data()

def get_mock_test_data():
    """返回模拟体测数据"""
    return {
        'height': '132',
        'weight': '28',
        'vital_capacity': '1800',
        'standing_long_jump': '120',
        'sit_and_reach': '15',
        'push_up': '15',
        'plank': '60',
        'risk_level': '低'
    }

# 提交体测数据
def submit_test_data(record_id, test_data):
    """提交体测数据到飞书"""
    token = get_feishu_token()
    if not token:
        print("⚠️  无法获取 token，模拟提交")
        print("📊 收到体测数据：")
        print(json.dumps(test_data, ensure_ascii=False, indent=2))
        return True
    
    # 构建飞书记录数据
    fields = {}
    
    # 学员姓名
    if 'student_name' in test_data:
        fields['学员姓名'] = test_data['student_name']
    
    # 测试日期 (毫秒时间戳)
    fields['测试日期'] = int(datetime.now().timestamp() * 1000)
    
    # 体能测试数据
    if 'vital_capacity' in test_data and test_data['vital_capacity']:
        try:
            fields['肺活量(ml)'] = float(test_data['vital_capacity'])
        except:
            pass
    
    if 'standing_long_jump' in test_data and test_data['standing_long_jump']:
        try:
            fields['立定跳远(cm)'] = float(test_data['standing_long_jump'])
        except:
            pass
    
    if 'sit_and_reach' in test_data and test_data['sit_and_reach']:
        try:
            fields['体前屈(cm)'] = float(test_data['sit_and_reach'])
        except:
            pass
    
    # 测试教练
    if 'coach_name' in test_data:
        fields['测试教练'] = test_data['coach_name']
    
    # 备注说明 (包含跪姿俯卧撑、平板支撑等)
    notes = []
    if 'push_up' in test_data and test_data['push_up']:
        notes.append(f"跪姿俯卧撑: {test_data['push_up']} 次")
    if 'plank' in test_data and test_data['plank']:
        notes.append(f"极限平板支撑: {test_data['plank']} 秒")
    if 'notes' in test_data and test_data['notes']:
        notes.append(test_data['notes'])
    
    if notes:
        fields['备注说明'] = '\n'.join(notes)
    
    # 提交到飞书
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_CONFIG['base_token']}/tables/{FEISHU_CONFIG['test_table_id']}/records"
    
    payload = {
        "fields": fields
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('code') == 0:
            new_record_id = result['data']['record']['record_id']
            print(f"✅ 数据已成功提交到飞书")
            print(f"   新记录ID: {new_record_id}")
            print(f"   提交数据: {json.dumps(fields, ensure_ascii=False)}")
            return True
        else:
            print(f"❌ 提交失败: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"❌ 提交失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# ========== 视频AI识别（硅基流动 API）==========

def extract_video_frames(video_path, max_frames=3):
    """提取视频关键帧，保存到临时目录
    使用 FFmpeg 或 cv2 进行帧提取
    """
    print(f"🎬 提取视频帧: {video_path}")
    frame_paths = []
    
    try:
        # 方法1：尝试使用 OpenCV (cv2)
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise Exception("无法打开视频")
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            print(f"   OpenCV检测: FPS={fps:.1f}, 总帧数={total_frames}, 时长={duration:.1f}秒")
            
            # 计算要提取的帧索引
            if total_frames <= max_frames:
                indices = list(range(total_frames))
            else:
                indices = [int(total_frames * (i+1) / (max_frames + 1)) for i in range(max_frames)]
            
            for i, idx in enumerate(indices):
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if ret:
                    output_path = os.path.join(TEMP_FRAME_DIR, f"frame_{i:02d}.jpg")
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    ts = idx / fps if fps > 0 else 0
                    print(f"   ✅ 帧 {i+1}/{len(indices)}: 索引={idx} 时间={ts:.1f}s -> {output_path}")
                    frame_paths.append(output_path)
            
            cap.release()
            print(f"✅ OpenCV提取成功，共 {len(frame_paths)} 帧")
            return frame_paths
            
        except ImportError:
            print("   OpenCV不可用，尝试FFmpeg...")
            
        # 方法2：尝试使用 FFmpeg
        try:
            import subprocess
            
            # 检查视频信息
            probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 
                        'format=duration,size:stream=r_frame_rate,nb_frames', 
                        '-of', 'json', video_path]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            
            if probe_result.returncode == 0:
                import json
                info = json.loads(probe_result.stdout)
                duration = float(info.get('format', {}).get('duration', 10))
                print(f"   FFprobe检测: 时长={duration:.1f}秒")
            else:
                duration = 10
                print(f"   FFprobe检测失败，使用默认时长 {duration} 秒")
            
            # 提取帧
            indices = [int(duration * (i+1) / (max_frames + 1)) for i in range(max_frames)]
            
            for i, ts in enumerate(indices):
                output_path = os.path.join(TEMP_FRAME_DIR, f"frame_{i:02d}.jpg")
                cmd = ['ffmpeg', '-y', '-ss', str(ts), '-i', video_path, 
                       '-vframes', '1', '-q:v', '2', output_path]
                
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0 and os.path.exists(output_path):
                    print(f"   ✅ 帧 {i+1}/{len(indices)}: 时间={ts:.1f}s -> {output_path}")
                    frame_paths.append(output_path)
                else:
                    print(f"   ⚠️  FFmpeg提取帧 {i} 失败")
            
            print(f"✅ FFmpeg提取成功，共 {len(frame_paths)} 帧")
            return frame_paths
            
        except ImportError:
            print("   FFmpeg不可用")
        except FileNotFoundError:
            print("   FFmpeg未安装")
            
    except Exception as e:
        print(f"   ❌ 提取帧失败: {e}")
        import traceback
        traceback.print_exc()
    
    return frame_paths


def analyze_frame_with_silicon_vl(frame_path, analysis_type="posture"):
    """
    使用硅基流动 Qwen3-VL 分析图像
    analysis_type: "foot_arch" | "posture" | "body_comp"
    """
    print(f"🧠 使用AI分析图像: {frame_path}")
    
    # 读取图像并转base64
    with open(frame_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')
    
    # 根据分析类型构建提示词（优化为识别屏幕截图中的数字）
    if analysis_type == "foot_arch":
        prompt = """这是一张足弓/足底压力测试设备的屏幕截图。请仔细识别屏幕上**所有的数字和文字**，不要遗漏任何数据。

逐行逐列扫描每个数据方块，读取所有数值。

请严格按照以下JSON格式返回（每个字段都必须填写）：
{
  "足弓类型": "如：正常足弓、扁平足、高足弓",
  "左前足压力": "如：46.8%",
  "左中足压力": "如：17.9%",
  "左后足压力": "如：35.4%",
  "右前足压力": "如：46.1%",
  "右中足压力": "如：16.0%",
  "右后足压力": "如：37.8%",
  "左足弓评分": "如：正常、偏低、偏高",
  "右足弓评分": "如：正常、偏低、偏高",
  "分析说明": "综合评估结果"
}

**重要**：
1. 逐行逐列扫描每个数据方块
2. 图片可能有多个截图拼接，每张都要完整读取
3. 数字+单位一起读出
4. 不要猜测，看到什么读什么
5. 如果某个位置确实没有数据，写"无"
"""
    elif analysis_type == "posture":
        prompt = """这是一张体态评估测试设备的屏幕截图。请仔细识别屏幕上**所有的数字、角度、指标名称和结果**，不要遗漏任何数据。

逐行逐列扫描每个数据方块，读取所有数值。

请严格按照以下JSON格式返回（每个字段都必须填写）：
{
  "头颈对称性": "如：对称、偏左2°、偏右3°",
  "头颈部倾斜": "如：正常、前倾2°",
  "肩部对称": "如：对称、左高2mm、右高3mm",
  "圆肩程度": "如：无、轻微5°、明显10°",
  "驼背程度": "如：无、轻微、明显",
  "躯干对称": "如：对称、左偏5mm",
  "重心偏移": "如：居中、左偏5mm、右偏8mm",
  "骨盆倾斜": "如：水平、左倾2°、右倾3°",
  "骨盆对称": "如：对称、左高3mm",
  "脊柱侧弯": "如：无、左侧弯5°、右侧弯3°",
  "综合评分": "如：85分、92分",
  "风险等级": "如：低风险、中风险、高风险",
  "分析说明": "综合评估结果"
}

**重要**：
1. 逐行逐列扫描每个数据方块
2. 图片可能有多个截图拼接，每张都要完整读取
3. 数字+单位一起读出（°、mm等）
4. 不要猜测，看到什么读什么
5. 如果某个位置确实没有数据，写"无"
"""
    else:  # body_comp
        prompt = """这是一张人体成分分析仪的屏幕截图。截图上显示了很多蓝色/黑色的方块，每个方块代表一个体成分指标。请非常仔细地逐个读取屏幕上**所有可见的数字和文字**，不要遗漏任何一个。

从上到下、从左到右，依次读取每个方块中的数据。

请严格按照以下JSON格式返回，每个字段都必须填写（读到的值或"无"）：
{
  "体重": "如：24.1kg",
  "BMI": "如：15.2",
  "体脂率": "如：20.1%",
  "肌肉率": "如：75.3%",
  "肌肉量": "如：18.1kg",
  "水分率": "如：54.8%",
  "水分量": "如：13.2kg",
  "骨重": "如：1.1kg",
  "基础代谢": "如：1011.0kcal",
  "蛋白率": "如：16.1%",
  "蛋白量": "如：3.9kg",
  "身体年龄": "如：6.0",
  "内脏脂肪指数": "如：1.0",
  "皮下脂肪率": "如：23.9%",
  "皮下脂肪量": "如：5.8kg",
  "脂肪量": "如：4.8kg",
  "标准体重": "如：33.6kg",
  "去脂体重": "如：19.3kg",
  "体重控制量": "如：9.5kg",
  "四肢肌肉指数": "如：7.1",
  "身体类型": "如：标准肌肉型",
  "肥胖等级": "如：体重不足",
  "体形判断": "如：标准肌肉型",
  "分析说明": "把所有识别到的数据汇总成一段话"
}

**关键要求**：
1. 逐行逐列扫描每个数据方块
2. 图片可能有3张截图拼接，每张截图都要完整读取
3. 数字旁边如果有单位（如kg、%、kcal），必须一起读出
4. 每个方块下面可能还有状态标签（如：偏瘦、标准、优、不足、偏高），也要读取
5. 不要猜测数据，看到什么就读什么
6. 如果某个位置确实没有数据，写"无"
"""
    
    # 调用硅基流动API
    url = f"{SILICON_FLOW_CONFIG['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {SILICON_FLOW_CONFIG['api_key']}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": SILICON_FLOW_CONFIG['vision_model'],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_data}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        "max_tokens": 500,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)  # 增加超时到120秒
        result = response.json()
        
        if response.status_code == 200 and "choices" in result:
            content = result["choices"][0]["message"]["content"]
            print(f"   AI返回: {content[:200]}...")
            
            # 尝试解析JSON
            try:
                # 提取JSON部分（可能有前缀/后缀文字）
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
            
            # 如果解析失败，返回原始文本
            return {"分析说明": content}
        else:
            print(f"   ❌ API调用失败: {result}")
            return None
    except Exception as e:
        print(f"   ❌ 分析失败: {e}")
        return None


def analyze_video(video_path, analysis_type="posture"):
    """
    分析视频：提取帧 → AI分析 → 汇总结果
    """
    print(f"\n{'='*60}")
    print(f"🎥 开始视频分析 (类型: {analysis_type})")
    print(f"   视频文件: {video_path}")
    print(f"{'='*60}\n")
    
    try:
        # 提取帧
        frames = extract_video_frames(video_path, max_frames=3)
        
        if not frames:
            return {"error": "无法提取视频帧，请确保视频格式正确（支持MP4、AVI、MOV等格式）"}
        
        # 分析每一帧
        results = []
        for frame in frames:
            try:
                result = analyze_frame_with_silicon_vl(frame, analysis_type)
                if result:
                    results.append(result)
            except Exception as e:
                print(f"   ⚠️ 分析帧失败: {e}")
        
        # 汇总结果
        if results:
            print(f"\n✅ 分析完成，共成功分析 {len(results)}/{len(frames)} 帧")
            return results[0]  # 返回第一帧的结果
        else:
            return {"error": "AI分析失败，所有帧分析均未成功"}
            
    except Exception as e:
        print(f"❌ 视频分析异常: {e}")
        import traceback
        traceback.print_exc()
        return {"error": f"视频分析出错: {str(e)[:100]}"}
    
    # 移除旧代码（已整合到上面的try-except中）
    # 保留函数结构以避免引用错误


def analyze_image(image_base64, analysis_type="posture"):
    """
    分析图片（比视频更快）
    image_base64: base64编码的图片数据
    """
    print(f"\n{'='*60}")
    print(f"🖼️ 开始图片分析 (类型: {analysis_type})")
    print(f"{'='*60}\n")
    
    try:
        # 解码base64图片到临时文件
        import tempfile
        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg', dir=TEMP_FRAME_DIR)
        temp_img_path = temp_img.name
        temp_img.close()
        
        with open(temp_img_path, 'wb') as f:
            f.write(base64.b64decode(image_base64))
        
        print(f"📷 接收到图片: {temp_img_path}, 大小: {os.path.getsize(temp_img_path)} bytes")
        
        # 分析图片
        result = analyze_frame_with_silicon_vl(temp_img_path, analysis_type)
        
        # 清理临时文件
        try:
            os.unlink(temp_img_path)
        except:
            pass
        
        if result:
            print(f"✅ 图片分析完成: {result}")
            return result
        else:
            return {"error": "AI分析失败，请稍后重试"}
            
    except Exception as e:
        print(f"❌ 图片分析失败: {e}")
        import traceback
        traceback.print_exc()
        return {"error": f"图片分析出错: {str(e)[:100]}"}


# ========== HTTP 请求处理 ==========

class Handler(BaseHTTPRequestHandler):
    # CORS 跨域配置
    def add_cors_headers(self):
        """添加 CORS 响应头"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "3600")
    
    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.add_cors_headers()
        self.end_headers()
    
    def do_GET(self):
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if path in ["/", "/index.html"]:
            self.send_html(f"{HTML_DIR}/教练端管理界面.html")
        elif path == "/test" or path.endswith("体测录入界面.html"):
            self.send_html(f"{HTML_DIR}/体测录入界面.html")
        elif path == "/api/students":
            students = get_students()
            self.send_json({"success": True, "data": students})
        elif path == "/api/get-test-data":
            record_id = params.get('record_id', [None])[0]
            if record_id:
                data = get_test_data(record_id)
                self.send_json({"success": True, "data": data})
            else:
                self.send_json({"success": False, "error": "缺少 record_id"})
        else:
            self.send_error(404)
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == "/api/submit-test":
            length = int(self.headers["Content-Length"])
            data = json.loads(self.rfile.read(length))
            record_id = data.get('record_id')
            success = submit_test_data(record_id, data)
            
            if success:
                self.send_json({"success": True, "message": "提交成功"})
            else:
                self.send_json({"success": False, "message": "提交失败"})
        
        elif path == "/api/analyze-video":
            # 视频AI分析端点
            try:
                length = int(self.headers["Content-Length"])
                data = json.loads(self.rfile.read(length))
                
                video_data = data.get('video_data')  # base64编码的视频
                analysis_type = data.get('analysis_type', 'posture')
                
                if not video_data:
                    self.send_json({"success": False, "error": "缺少视频数据"})
                    return
                
                print(f"📹 收到视频分析请求: 类型={analysis_type}, 数据长度={len(video_data)}")
                
                # 解码base64视频到临时文件
                import tempfile
                temp_video = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', dir=TEMP_FRAME_DIR)
                temp_video_path = temp_video.name
                temp_video.close()
                
                try:
                    with open(temp_video_path, 'wb') as f:
                        f.write(base64.b64decode(video_data))
                    
                    video_size_mb = os.path.getsize(temp_video_path) / 1024 / 1024
                    print(f"📹 解码视频成功: {temp_video_path}, 大小: {video_size_mb:.2f} MB")
                    
                    # 检查视频文件是否有效
                    if video_size_mb < 0.01:
                        raise Exception("视频文件过小，可能是无效数据")
                    
                    # 分析视频
                    print("🔄 开始AI视频分析...")
                    result = analyze_video(temp_video_path, analysis_type)
                    
                    if 'error' in result:
                        self.send_json({"success": False, "error": result['error']})
                    else:
                        self.send_json({"success": True, "data": result})
                        
                finally:
                    # 清理临时文件
                    try:
                        if os.path.exists(temp_video_path):
                            os.unlink(temp_video_path)
                    except:
                        pass
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                self.send_json({"success": False, "error": "请求数据格式错误"})
            except base64.binascii.Error as e:
                print(f"❌ Base64解码失败: {e}")
                self.send_json({"success": False, "error": "视频数据格式错误"})
            except Exception as e:
                import traceback
                print(f"❌ 视频分析失败: {e}")
                traceback.print_exc()
                self.send_json({"success": False, "error": f"视频分析出错: {str(e)[:100]}"})
        
        elif path == "/api/submit-booking":
            # 预约提交端点
            try:
                length = int(self.headers["Content-Length"])
                data = json.loads(self.rfile.read(length))
                
                result = submit_booking(data)
                
                if result.get('success'):
                    self.send_json({"success": True, "record_id": result.get('record_id')})
                else:
                    self.send_json({"success": False, "message": result.get('message', '提交失败')})
            except Exception as e:
                import traceback
                print(f"❌ 预约提交失败: {e}")
                traceback.print_exc()
                self.send_json({"success": False, "message": str(e)})

        elif path == "/api/debug-env":
            # 调试端点：返回环境变量配置
            self.send_json({
                "booking_table_id": FEISHU_CONFIG['booking_table_id'],
                "table_id": FEISHU_CONFIG['table_id'],
                "base_token": FEISHU_CONFIG['base_token'],
                "status": "ok"
            })
        elif path == "/api/analyze-image":
            # 图片AI分析端点（比视频更快）
            try:
                length = int(self.headers["Content-Length"])
                data = json.loads(self.rfile.read(length))
                
                image_data = data.get('image_data')  # base64编码的图片
                analysis_type = data.get('analysis_type', 'posture')
                
                if not image_data:
                    self.send_json({"success": False, "error": "缺少图片数据"})
                    return
                
                # 分析图片
                result = analyze_image(image_data, analysis_type)
                
                if 'error' in result:
                    self.send_json({"success": False, "error": result['error']})
                else:
                    self.send_json({"success": True, "data": result})
                    
            except Exception as e:
                import traceback
                print(f"❌ 图片分析失败: {e}")
                traceback.print_exc()
                self.send_json({"success": False, "error": str(e)})
        
        else:
            self.send_error(404)
    
    def send_html(self, filepath):
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)
    
    def send_json(self, data):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.add_cors_headers()
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")

def main():
    port = int(os.environ.get('PORT', 8082))
    server = HTTPServer(("0.0.0.0", port), Handler)
    
    print("=" * 60)
    print("🏋️ 邻练体育 - 教练端服务器")
    print("=" * 60)
    print(f"✅ 服务器启动成功！监听端口: {port}")
    print()
    print(f"📊 API接口：")
    print(f"   GET  /api/students - 获取学生列表")
    print(f"   POST /api/submit-test - 提交体测数据")
    print()
    print(f"✅ 飞书配置：")
    print(f"   App ID: {FEISHU_CONFIG['app_id']}")
    print(f"   App Secret: 已配置")
    print(f"   多维表格: {FEISHU_CONFIG['base_token']}")
    print()
    print(f"🛑 按 Ctrl+C 停止服务器")
    print("=" * 60)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止")
        server.shutdown()

if __name__ == "__main__":
    main()
