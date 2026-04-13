import { openHands } from "#/api/open-hands-axios";

export interface FileUploadResult {
  upload_id: string;
  filename: string;
  size_bytes: number;
  sandbox_path: string;
}

export class FileUploadService {
  static async upload(file: File): Promise<FileUploadResult> {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await openHands.post<FileUploadResult>(
      "/api/v1/uploads",
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return resp.data;
  }
}
