from db.config import db

# --- Insert ---
insert_artist = lambda item: db.insert("artist", item)
insert_collection = lambda item: db.insert("collection", item)
insert_track = lambda item: db.insert("track", item)

# --- Get by ID ---
get_artist_db = lambda artist_id: db.get_by_id("artist", artist_id)
get_collection_db = lambda collection_id: db.get_by_id("collection", collection_id)
get_track_db = lambda track_id: db.get_by_id("track", track_id)

# --- Relations ---
get_artist_tracks = lambda artist_id: db.get_artist_tracks(artist_id)
get_artist_collections = lambda artist_id: db.get_artist_collections(artist_id)
get_collection_tracks = lambda collection_id: db.get_collection_tracks(collection_id)

# --- Cache ---
get_cache = lambda cache_id: db.get_cache(cache_id)
set_cache = lambda item: db.insert("cache", item)
# --- Cache ---
insert_search_cache = lambda search_id, type_, term, data: db.insert_search_cache(search_id=search_id, type_=type_,
                                                                                  term=term, data=data)
get_search_cache = lambda search_id: db.get_search_cache(search_id=search_id)

# --- Users ---
insert_user = lambda user_id: db.insert_user(user_id)
get_users_db = lambda user_id: db.get_user_exists(user_id)
get_all_users = lambda: db.get_all_users()

# --- Search ---
local_search = lambda term, entity="all": db.search(term, entity)

# --- Init ---
init_db = lambda: db.init()
