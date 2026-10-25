// The native stack does not need Gesture Handler; excluding it also keeps its
// generated Fabric codegen out of the Android build, whose mirrored source path
// is one of the longest in the project. If a future screen uses a gesture
// handler view, remove this exclusion and the import will work again.
module.exports = {
  dependencies: {
    'react-native-gesture-handler': {
      platforms: {
        android: null,
      },
    },
  },
};
