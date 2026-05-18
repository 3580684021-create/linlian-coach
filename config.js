// 邻练体育 - 前端配置文件
// 部署时修改此文件的 API_BASE_URL

// 本地开发
// const API_BASE_URL = 'http://localhost:8082';

// Nginx反向代理模式 - 使用相对路径（前端和后端同域部署）
const API_BASE_URL = '';

// 导出供其他脚本使用
window.API_BASE_URL = API_BASE_URL;
