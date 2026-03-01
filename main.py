def _populate_preview_tree(self, items):
    """Populate the preview tree with items"""
    for item in items:
        # Add item to the preview tree
        self.preview_tree.add(item)
        self.preview_tree.update()  # Update tree view after each addition
        
def _insert_path(self, path):
    """Insert a path into the appropriate data structure"""
    if path in self.paths:
        return  # Path already exists
    self.paths.append(path)  # Add new path
    self.update_view()  # Ensure the view is updated after insertion
