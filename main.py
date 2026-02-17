def _populate_preview_tree(data):
    """ Populate the preview tree with given data and handle errors. """
    try:
        if data is None:
            raise ValueError('Provided data is None.')
        if not isinstance(data, list):
            raise TypeError('Expected data to be a list.')

        tree = {}  # Initialize the tree dictionary
        for entry in data:
            path = entry.get('path', None)
            if not path:
                raise ValueError(f'Empty or null path found in entry: {entry}')

            # Split the path into parts
            parts = path.split('/')
            current = tree

            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]  # Move into the next level

        return tree
    except Exception as e:
        print(f'Error populating preview tree: {str(e)}')
        return {}


def _insert_path(tree, path):
    """ Insert a path into the tree structure with error checking. """ 
    try:
        if not path:
            raise ValueError('Provided path is empty or null.')

        # Split the path into parts
        parts = path.split('/')
        current = tree

        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]  # Move deeper into the tree

    except Exception as e:
        print(f'Error inserting path: {str(e)}')
