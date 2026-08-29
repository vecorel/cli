SUPPORTED_PROTOCOLS = ["http", "https", "s3", "gs"]

COMPRESSION_METHODS = ["brotli", "gzip", "lz4", "snappy", "zstd", "none"]

GEOPARQUET_VERSIONS = ["1.0.0", "1.1.0"]
GEOPARQUET_DEFAULT_VERSION = "1.1.0"

# Default level used when sorting features along a Hilbert curve. A level of N
# splits each axis of the reference bounds into 2**N cells; 16 gives a
# 65,536 x 65,536 grid, fine enough for world-scale references at sub-km
# resolution near the equator.
HILBERT_DEFAULT_LEVEL = 16
