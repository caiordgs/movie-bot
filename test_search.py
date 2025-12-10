# test_search.py
from tmdb_client import search_movie

def main():
    # por enquanto só testa se importa e chama search_movie (quando implementada)
    try:
        resp = search_movie("john wick")
    except NotImplementedError:
        print("search_movie ainda não implementada — esqueleto ok.")
        return
    except Exception as e:
        print("Erro ao chamar search_movie:", e)
        return

    if not resp:
        print("Resposta vazia ou erro.")
    else:
        results = resp.get("results", [])
        print(f"Total results: {len(results)}")
        if results:
            first = results[0]
            title = first.get("title") or first.get("name")
            year = first.get("release_date", "")[:4]
            vote = first.get("vote_average")
            print(f"1) {title} ({year}) — Nota: {vote} — ID: {first.get('id')}")

if __name__ == "__main__":
    main()
