import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Product media library (Hub backend) — kiểu WP Media Library:
//   GET    /products/media/        -> getMediaImages / useMediaImages
//       params: ?page, ?page_size, ?search
//   POST   /products/media/        -> uploadMediaImage / useUploadMedia (multipart)
//   DELETE /products/media/{id}/   -> deleteMediaImage / useDeleteMedia
// The returned `url` is absolute; it is what gets stored in the product's
// `images` array or embedded in description HTML. The backend pushes those
// URLs to WooCommerce as-is — the frontend never talks to Woo.

export const getMediaImages = (params = {}) =>
  api.get("/products/media/", { params }).then((r) => r.data);

export const uploadMediaImage = (file) => {
  const form = new FormData();
  form.append("image", file);
  return api.post("/products/media/", form).then((r) => r.data);
};

export const deleteMediaImage = (id) =>
  api.delete(`/products/media/${id}/`).then((r) => r.data);

const KEY = ["media"];

export function useMediaImages(params = {}) {
  return useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: () => getMediaImages(params),
  });
}

export function useUploadMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: uploadMediaImage,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteMediaImage,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
