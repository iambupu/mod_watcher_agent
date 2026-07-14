import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import {
  addFavorite,
  removeFavorite,
  type FavoriteRef,
} from "@/api/favorites";

interface UseFavoriteToggleOptions {
  favoriteByModId: Map<number, FavoriteRef>;
  invalidateQueryKeys?: QueryKey[];
}

export function useFavoriteToggle({
  favoriteByModId,
  invalidateQueryKeys = [["favorites"]],
}: UseFavoriteToggleOptions) {
  const queryClient = useQueryClient();
  const favoriteMutation = useMutation({
    mutationFn: async (modId: number) => {
      const favorite = favoriteByModId.get(modId);
      if (favorite) {
        await removeFavorite(favorite.id);
        return;
      }
      await addFavorite({ mod_id: modId });
    },
    onSuccess: async () => {
      await Promise.all(
        invalidateQueryKeys.map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
    },
  });

  return {
    favoriteMutation,
    toggleFavorite: favoriteMutation.mutateAsync,
  };
}
