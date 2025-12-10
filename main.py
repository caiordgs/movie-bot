# main.py (ATUALIZADO)
import sys
from tmdb_client import (
    search_movie,
    discover_movies,
    get_recommendations,
    get_genres,
    pretty_print_results,
    filter_results_by_min_votes,
    normalize_text
)
from favorites import add_favorite, list_favorites, remove_favorite, top_genres_from_favorites, is_favorite
from logger_conf import get_logger

logger = get_logger(__name__)
DEFAULT_MIN_VOTES = 30

def ask_int(prompt: str, allow_empty: bool = True):
    val = input(prompt).strip()
    if val == "" and allow_empty:
        return None
    if val.isdigit():
        return int(val)
    print("Valor inválido — ignorando.")
    return None

# (handle_search etc. are adapted to support pagination and favoritar)
def handle_search(last_results: list):
    page = 1
    while True:
        term = input("Digite termo de busca (ex: 'john wick' ou 'matrix'): ").strip()
        if not term:
            print("Termo vazio — tente de novo.")
            return last_results

        resp = search_movie(term, page=page)
        if not resp:
            print("Resposta vazia ou erro na API.")
            return last_results

        results = resp.get("results", [])
        total_pages = resp.get("total_pages", 1)
        total_results = resp.get("total_results", len(results))

        min_votes = ask_int(f"Número mínimo de avaliações (enter = {DEFAULT_MIN_VOTES}): ")
        min_votes = min_votes if min_votes is not None else DEFAULT_MIN_VOTES

        filtered = filter_results_by_min_votes(results, min_votes=min_votes)
        total_before = len(results)
        total_after = len(filtered)

        if total_after == 0 and total_before > 0:
            print(f"Filtro por ≥ {min_votes} avaliações removeu todos os {total_before} resultados. Mostrando os top {min(5, total_before)} originais:")
            pretty_print_results(results, limit=5)
            last_results = results[:5]
        else:
            print(f"Página {page}/{total_pages} — {total_after} de {total_before} resultados têm ≥ {min_votes} avaliações — mostrando os top {min(5, total_after)}:")
            pretty_print_results(filtered, limit=5)
            last_results = filtered[:5]

        # ações pós-busca: favoritar / next page / voltar ao menu
        print("\nAções: [f] favoritar um item, [n] próxima página, [p] página anterior, [m] menu")
        action = input("> ").strip().lower()
        if action == "f":
            choice = input("Escolha número para favoritar (1..5): ").strip()
            if choice.isdigit():
                idx = int(choice)-1
                if 0 <= idx < len(last_results):
                    movie = last_results[idx]
                    ok = add_favorite(movie)
                    if ok:
                        logger.info(f"Favoritado: {movie.get('title')} ({movie.get('id')})")
                        print("Favorito adicionado.")
                    else:
                        print("Já era favorito.")
                else:
                    print("Índice inválido.")
            continue  # permanece na mesma página
        elif action == "n":
            if page < total_pages:
                page += 1
                continue
            else:
                print("Você já está na última página.")
                continue
        elif action == "p":
            if page > 1:
                page -= 1
                continue
            else:
                print("Você já está na primeira página.")
                continue
        else:
            return last_results

def handle_genre(last_results: list, genres_map: dict):
    g_input = input("Digite o gênero (ex: acao, comedia) ou 'lista' para ver opções: ").strip()
    if not g_input:
        print("Gênero vazio — tente de novo.")
        return last_results

    if g_input.lower() == "lista":
        if not genres_map:
            print("Mapa de gêneros vazio (não foi possível carregar gêneros).")
            return last_results
        print("Gêneros disponíveis:")
        for name in sorted(genres_map.keys()):
            print(" -", name)
        return last_results

    normalized = normalize_text(g_input)
    genre_id = genres_map.get(normalized)
    if not genre_id:
        found = [(n, i) for n, i in genres_map.items() if normalized in n]
        if len(found) == 1:
            genre_id = found[0][1]
            print(f"Interpretado gênero como: {found[0][0]}")
        elif len(found) > 1:
            print("Gêneros possíveis encontrados:")
            for n, i in found:
                print(f" - {n} (id {i})")
            print("Seja mais específico.")
            return last_results
        else:
            print("Gênero não encontrado. Use 'lista' para ver opções.")
            return last_results

    year = ask_int("Filmes de qual ano? (enter para pular): ")
    min_votes = ask_int(f"Número mínimo de avaliações (enter = {DEFAULT_MIN_VOTES}): ")
    min_votes = min_votes if min_votes is not None else DEFAULT_MIN_VOTES

    params = {"genre_id": genre_id, "min_vote_count": min_votes}
    if year:
        params["year"] = year

    resp = discover_movies(params)
    if not resp:
        print("Resposta vazia ou erro no discover.")
        return last_results

    results = resp.get("results", [])
    if not results:
        print("Nenhum filme encontrado com esses filtros.")
        return last_results

    filtered = filter_results_by_min_votes(results, min_votes=min_votes)
    if not filtered:
        print(f"Nenhum resultado com ≥ {min_votes} avaliações. Mostrando os top {min(5, len(results))} originais:")
        pretty_print_results(results, limit=5)
        last_results = results[:5]
    else:
        pretty_print_results(filtered, limit=5)
        last_results = filtered[:5]

    return last_results

def handle_recommendations(last_results: list):
    if not last_results:
        print("Não há resultados anteriores. Faça uma busca primeiro.")
        return last_results

    print("Escolha o número do filme da última listagem (1..N):")
    pretty_print_results(last_results, limit=len(last_results))
    choice = input("Número: ").strip()
    if not choice.isdigit():
        print("Escolha inválida.")
        return last_results
    idx = int(choice) - 1
    if idx < 0 or idx >= len(last_results):
        print("Índice fora do intervalo.")
        return last_results

    movie_id = last_results[idx].get("id")
    if not movie_id:
        print("ID do filme não disponível.")
        return last_results

    min_votes = ask_int(f"Número mínimo de avaliações para recomendações (enter = {DEFAULT_MIN_VOTES}): ")
    min_votes = min_votes if min_votes is not None else DEFAULT_MIN_VOTES

    rec = get_recommendations(movie_id)
    if not rec:
        print("Nenhuma recomendação retornada ou erro.")
        return last_results

    recs = rec.get("results", [])
    recs_filtered = filter_results_by_min_votes(recs, min_votes=min_votes)
    if not recs_filtered:
        print(f"Nenhuma recomendação com ≥ {min_votes} avaliações — mostrando recomendações originais (top 5):")
        pretty_print_results(recs, limit=5)
        last_results = recs[:5]
    else:
        pretty_print_results(recs_filtered, limit=5)
        last_results = recs_filtered[:5]

    return last_results

# Novas funções relacionadas a favoritos
def handle_list_favorites():
    favs = list_favorites()
    if not favs:
        print("Nenhum favorito salvo.")
        return
    print("Seus favoritos:")
    pretty_print_results(favs, limit=len(favs))

def handle_remove_favorite():
    favs = list_favorites()
    if not favs:
        print("Nenhum favorito para remover.")
        return
    pretty_print_results(favs, limit=len(favs))
    choice = input("Digite o número do favorito para remover (1..N): ").strip()
    if not choice.isdigit():
        print("Escolha inválida.")
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(favs):
        print("Índice inválido.")
        return
    movie_id = favs[idx].get("id")
    if not movie_id:
        print("ID não encontrado.")
        return
    ok = remove_favorite(movie_id)
    if ok:
        logger.info(f"Removido favorito: {favs[idx].get('title')} ({movie_id})")
        print("Removido.")
    else:
        print("Não foi possível remover.")

def handle_recommend_from_favorites():
    favs = list_favorites()
    if not favs:
        print("Nenhum favorito salvo. Adicione favoritos primeiro.")
        return
    top_genres = top_genres_from_favorites(top_n=3)
    if not top_genres:
        print("Nenhum gênero encontrado a partir dos favoritos.")
        return
    print(f"Top gêneros dos seus favoritos: {top_genres} (ids). Iremos buscar recomendações por esses gêneros.")
    # chama discover para cada gênero, junta resultados e remove duplicatas
    aggregate = []
    seen_ids = set()
    for gid in top_genres:
        resp = discover_movies({"genre_id": gid, "min_vote_count": DEFAULT_MIN_VOTES, "sort_by": "vote_average.desc"})
        if not resp:
            continue
        for item in resp.get("results", []):
            mid = item.get("id")
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            aggregate.append(item)
    if not aggregate:
        print("Nenhuma recomendação encontrada via favoritos.")
        return
    print(f"Mostrando top {min(10, len(aggregate))} recomendações baseadas nos seus favoritos:")
    pretty_print_results(aggregate, limit=10)

def input_loop():
    genres_map = get_genres() or {}
    if genres_map:
        print(f"Mapeados {len(genres_map)} gêneros. Use 'lista' no comando genero para ver.")
    else:
        print("Não foi possível carregar gêneros — funcionalidade de gênero pode ficar limitada.")

    last_results = []

    while True:
        print("\nO que você quer fazer? (buscar / genero / recomendacoes / favoritos / favoritar / remover / recomendar_favs / sair)")
        cmd = input("> ").strip().lower()

        if cmd in ("sair", "exit", "quit"):
            print("Tchau! Até a próxima.")
            sys.exit(0)

        if cmd in ("buscar", "search"):
            last_results = handle_search(last_results)

        elif cmd in ("genero", "gênero", "genre"):
            last_results = handle_genre(last_results, genres_map)

        elif cmd in ("recomendacoes", "recomendações", "recommendations"):
            last_results = handle_recommendations(last_results)

        elif cmd == "favoritar":
            # atalho: pede um ID manualmente ou usa ultimo resultados
            if not last_results:
                print("Sem resultados recentes para favoritar. Faça uma busca primeiro.")
                continue
            pretty_print_results(last_results, limit=len(last_results))
            choice = input("Escolha número para favoritar (1..N): ").strip()
            if not choice.isdigit():
                print("Escolha inválida.")
                continue
            idx = int(choice) - 1
            if idx < 0 or idx >= len(last_results):
                print("Índice inválido.")
                continue
            movie = last_results[idx]
            ok = add_favorite(movie)
            if ok:
                logger.info(f"Favoritado via comando: {movie.get('title')} ({movie.get('id')})")
                print("Favorito adicionado.")
            else:
                print("Já era favorito.")

        elif cmd == "favoritos":
            handle_list_favorites()

        elif cmd == "remover":
            handle_remove_favorite()

        elif cmd == "recomendar_favs":
            handle_recommend_from_favorites()

        else:
            print("Comando não reconhecido. Use: buscar / genero / recomendacoes / favoritos / favoritar / remover / recomendar_favs / sair")


if __name__ == "__main__":
    try:
        input_loop()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário. Até mais.")
        sys.exit(0)
