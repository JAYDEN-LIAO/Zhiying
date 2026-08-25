/* ════════════════════════════════════════════════════════════
   subjectsMock → 素材库对接层（v0.6，后端已实现，mock 退役）

   产品原设计：后端 subjects 接口未落地时，用 DEV 假数据预览完整交互。
   后端 15 个接口现已实现，故退役内存 mock，直连真实后端。

   保留 subjectsApi / subjectPhotoUrl / subjectPrimaryUrl 三个导出，
   ImageLibrary / AddSubjectDrawer 的 import 无需改动，直接走真实后端。
   告警（listSubjectAlerts）本期不做（决策 E），故不在此导出。
   ════════════════════════════════════════════════════════════ */

import { api } from "../services/api";

export const subjectsApi = {
  listImageSubjects: api.listImageSubjects.bind(api),
  listSubjectTags: api.listSubjectTags.bind(api),
  getImageSubject: api.getImageSubject.bind(api),
  createImageSubject: api.createImageSubject.bind(api),
  updateImageSubject: api.updateImageSubject.bind(api),
  deleteImageSubject: api.deleteImageSubject.bind(api),
  listSubjectPhotos: api.listSubjectPhotos.bind(api),
  uploadSubjectPhoto: api.uploadSubjectPhoto.bind(api),
  importCaseAssetPhoto: api.importCaseAssetPhoto.bind(api),
  updateSubjectPhoto: api.updateSubjectPhoto.bind(api),
  deleteSubjectPhoto: api.deleteSubjectPhoto.bind(api),
};

export function subjectPhotoUrl(subjectId: string, photoId: string): string {
  return api.getSubjectPhotoUrl(subjectId, photoId);
}

export function subjectPrimaryUrl(subjectId: string): string {
  return api.getSubjectPrimaryPhotoUrl(subjectId);
}
