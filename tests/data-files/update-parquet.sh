vec create-geoparquet ./tests/data-files/inspire.json ./tests/data-files/inspire2.json -o ./tests/data-files/inspire.parquet
vec create-geoparquet ./tests/data-files/mixed-invalid.json -o ./tests/data-files/mixed-invalid.parquet
vec create-geoparquet ./tests/data-files/mixed.json -o ./tests/data-files/mixed.parquet
# The de-sh.parquet is created by running the convert tests and copying the created file from the temp directory
