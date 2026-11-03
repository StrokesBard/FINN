"""Model-assisted extraction for what rules and parsing cannot reach (text inside filing PDFs).

The model only describes; rules still classify and rank. Every model claim must
quote the document, and output whose quote is not found in the document is
discarded before it can reach the screen.
"""
