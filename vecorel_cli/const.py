SUPPORTED_PROTOCOLS = ["http", "https", "s3", "gs"]

# Sent on every outgoing HTTP request. Some servers reject the default agents of
# the underlying libraries, e.g. geoportal.saarland.de answers 403 to any agent
# containing "aiohttp", which is what fsspec sends.
USER_AGENT = "vecorel-cli"

COMPRESSION_METHODS = ["brotli", "gzip", "lz4", "snappy", "zstd", "none"]

GEOPARQUET_VERSIONS = ["1.0.0", "1.1.0"]
GEOPARQUET_DEFAULT_VERSION = "1.1.0"

# Default level used when sorting features along a Hilbert curve. A level of N
# splits each axis of the reference bounds into 2**N cells; 16 gives a
# 65,536 x 65,536 grid, fine enough for world-scale references at sub-km
# resolution near the equator.
HILBERT_DEFAULT_LEVEL = 16
