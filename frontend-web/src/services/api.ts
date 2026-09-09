// 后端对接层共享实现见 frontend-shared/ —— 双端复用同一份，后端接口/字段变更只改一处
import { api as realApi } from "../../../frontend-shared/api";
import { wrapWithMock } from "./mock";

export * from "../../../frontend-shared/api";

/* Mock 演示模式：mock-* 视频 ID 直连 public/mock 本地文件；
   后端不可达时数据请求自动降级为本地演示数据（见 services/mock.ts） */
export const api = wrapWithMock(realApi);
