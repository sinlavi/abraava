from ytmusicapi import YTMusic

# Initialize the YTMusic object
ytmusic = YTMusic()

# Define your search query
query = "Daft Punk"

# Perform the search
# The 'filter' parameter can be: 'songs', 'videos', 'albums', 'artists', 'playlists', 'community_playlists', 'featured_playlists', 'uploads'.
# If you leave the filter blank, it returns a mix of everything.
results = ytmusic.search(query, filter="songs")

# Iterate through the results and print the details
for item in results:
    title = item.get('title')
    
    # Artists is usually a list of dictionaries
    artists_list = item.get('artists', [])
    artists = ", ".join([artist['name'] for artist in artists_list])
    
    video_id = item.get('videoId')
    album = item.get('album', {}).get('name') if item.get('album') else "Unknown Album"
    
    print(f"Title: {title}")
    print(f"Artist(s): {artists}")
    print(f"Album: {album}")
    print(f"Link: https://music.youtube.com/watch?v={video_id}")
    print("-" * 40)
