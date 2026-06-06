# Reference

## Theme

The package exposes `justdocs` as an MkDocs theme entry point.

## Search

Search indexes rendered pages linked from primary navigation.

## Smart Links

The justdocs-linker plugin resolves Service Discovery and Deployment Guide references from page and heading titles.

## Complexity

| Operation | Time | Space |
| --- | --- | --- |
| Theme asset check | O(n) | O(n) |
| Search scoring | O(p * q) | O(p) |
| Smart link pass | O(p * t * s) | O(t + s) |
