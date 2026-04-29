module.exports = new Proxy({}, {
  get: function(_target, prop) {
    return function(props) {
      return props?.children || null
    }
  }
})
