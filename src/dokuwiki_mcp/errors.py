class DokuWikiError(Exception):
    """Exception raised for API errors from DokuWiki."""
    
    def __init__(self, code: int, message: str, context: str = ""):
        self.code = code
        self.message = message
        self.context = context
        self.llm_explanation = self._get_llm_explanation(code)
        super().__init__(f"DokuWiki API Error {code}: {message}")

    def _get_llm_explanation(self, code: int) -> str:
        explanations = {
            111: "User is not authorized. The agent lacks permissions to read this page.",
            121: "Page does not exist. Suggest creating it or checking the namespace.",
            131: "Empty or invalid page ID given. Ensure the page ID is correctly formatted.",
            132: "Refusing to write an empty new wiki page. Provide content for the page.",
            133: "The page is currently locked by another user. Try again later.",
            134: "The page content was blocked (e.g., by a spam filter or wordblock). Review the content.",
            211: "User is not authorized. The agent lacks permissions to read this media file.",
            212: "User is not authorized. The agent lacks permissions to delete this media file.",
            221: "The requested media file does not exist. Check the namespace and filename.",
            231: "Empty or invalid media ID given. Ensure the file ID is correctly formatted.",
            232: "Media file is still referenced. It must be removed from all pages before deletion.",
            233: "Failed to delete media file. Check server permissions.",
            234: "Invalid base64 encoded data. Ensure the media file is correctly encoded.",
            235: "Empty file given. The media file has no content.",
            236: "Failed to save media. Check server disk space and permissions.",
            32602: "Invalid parameters. Ensure the payload matches the expected schema exactly.",
        }
        return explanations.get(code, "An unexpected API error occurred. Review the error message.")